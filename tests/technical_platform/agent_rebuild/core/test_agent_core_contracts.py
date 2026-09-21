"""S02 契约测试：纯 Python Agent Core + Fake Runtime。

验收目标（任务书 S02）：
- Core 目录无 PySide import；
- Fake Model 完成直接回答；
- Fake Model 完成一次和多次 ToolCall；
- 所有事件 JSON 可序列化；
- abort、失败和 late result 有确定行为。
"""
import asyncio
import json
from pathlib import Path

import pytest

CORE = Path(__file__).resolve().parents[4] / 'src/asset_based_agent/technical_platform/agent_core'

REQUIRED_ERROR_CODES = {
    'agent.invalid_request', 'agent.context_overflow', 'agent.operation_busy',
    'agent.cancelled', 'model.auth_failed', 'model.balance_insufficient',
    'model.timeout', 'model.protocol_error', 'model.billing_reconciliation',
    'tool.invalid_arguments', 'tool.permission_denied', 'tool.failed',
    'tool.unknown_outcome', 'session.stale_revision', 'session.corrupted',
    'resource.version_changed',
}


def run(coro):
    return asyncio.run(coro)


# ------------------------------------------------------------------ 环境门禁

def test_core_has_no_pyside_dependency():
    import re

    from asset_based_agent.technical_platform import agent_core  # noqa: F401
    sources = list(CORE.glob('*.py'))
    assert sources, 'agent_core 目录必须存在且包含模块'
    pattern = re.compile(r'^\s*(import|from)\s+PySide', re.MULTILINE)
    for path in sources:
        assert not pattern.search(path.read_text(encoding='utf-8')), \
            f'{path.name} 依赖 PySide'


def test_required_error_codes_exist():
    from asset_based_agent.technical_platform.agent_core import errors
    assert REQUIRED_ERROR_CODES <= set(errors.ERROR_CODES)
    for code in REQUIRED_ERROR_CODES:
        exc_class = errors.error_class_for(code)
        assert issubclass(exc_class, errors.AgentError)
        assert exc_class('x').code == code


# ------------------------------------------------------------------ 构建 fake 环境

def make_runtime(model_events_per_turn, tools=()):
    from asset_based_agent.technical_platform.agent_core.fakes import (
        FakeModelPort,
        InMemorySessionRepo,
    )
    from asset_based_agent.technical_platform.agent_core.runtime import AgentKernel
    repo = InMemorySessionRepo()
    repo.create_session('s1', project_id='p1', owner_id='alice', title='会话')
    model = FakeModelPort(model_events_per_turn)
    kernel = AgentKernel(repo=repo, model=model, tools=list(tools))
    return kernel, repo, model


def text_turn(text):
    from asset_based_agent.technical_platform.agent_core.contracts import ModelEvent
    return [ModelEvent('message_start', {}), ModelEvent('text_delta', {'text': text}),
            ModelEvent('message_complete', {})]


def tool_call_turn(name, arguments, call_id='c1'):
    from asset_based_agent.technical_platform.agent_core.contracts import ModelEvent
    return [ModelEvent('message_start', {}),
            ModelEvent('tool_call_complete', {'id': call_id, 'name': name, 'arguments': arguments}),
            ModelEvent('message_complete', {})]


# ------------------------------------------------------------------ 直接回答

def test_fake_model_direct_answer_commits_user_and_assistant():
    kernel, repo, _model = make_runtime([text_turn('你好，我是助手。')])
    events = []
    kernel.subscribe(events.append)
    accepted = run(kernel.submit('s1', 'main', {'text': '你好'}))
    assert accepted.operation_id
    entries = repo.entries('s1', 'main')
    assert [e.entry_type for e in entries] == ['user_message', 'assistant_message']
    assert entries[1].payload['text'] == '你好，我是助手。'
    operation = repo.get_operation(accepted.operation_id)
    assert operation.status == 'completed'
    # 每个事件都可 JSON 序列化，且事件类型在协议内
    kinds = {e.event_type for e in events}
    assert {'operation_accepted', 'turn_started', 'message_committed',
            'operation_completed'} <= kinds
    for event in events:
        json.dumps(event.to_dict())


# ------------------------------------------------------------------ 工具调用

def test_single_tool_call_round_trip():
    from asset_based_agent.technical_platform.agent_core.fakes import FakeTool
    echo = FakeTool('echo', handler=lambda args: {'echo': args['value']},
                    input_schema={'required': ['value']})
    kernel, repo, model = make_runtime(
        [tool_call_turn('echo', {'value': '数据'}), text_turn('结果是数据')], tools=[echo])
    accepted = run(kernel.submit('s1', 'main', {'text': '回声'}))
    entries = repo.entries('s1', 'main')
    kinds = [e.entry_type for e in entries]
    assert kinds == ['user_message', 'tool_call', 'tool_result', 'assistant_message']
    assert entries[1].payload['name'] == 'echo'
    assert entries[2].payload['result']['echo'] == '数据'
    assert echo.calls == [{'value': '数据'}]
    assert repo.get_operation(accepted.operation_id).status == 'completed'
    assert [descriptor.name for descriptor in model.requests[0].tools] == ['echo']


def test_multiple_tool_calls_across_turns():
    from asset_based_agent.technical_platform.agent_core.fakes import FakeTool
    tool = FakeTool('step', handler=lambda args: {'n': args['n'] + 1},
                    input_schema={'required': ['n']})
    kernel, repo, _model = make_runtime(
        [tool_call_turn('step', {'n': 1}, 'c1'),
         tool_call_turn('step', {'n': 2}, 'c2'),
         text_turn('完成')], tools=[tool])
    accepted = run(kernel.submit('s1', 'main', {'text': '两步'}))
    kinds = [e.entry_type for e in repo.entries('s1', 'main')]
    assert kinds == ['user_message', 'tool_call', 'tool_result',
                     'tool_call', 'tool_result', 'assistant_message']
    assert tool.calls == [{'n': 1}, {'n': 2}]
    assert repo.get_operation(accepted.operation_id).status == 'completed'


def test_each_model_turn_has_a_distinct_idempotency_request_id():
    from asset_based_agent.technical_platform.agent_core.fakes import FakeTool

    tool = FakeTool('step', handler=lambda args: {'n': args['n'] + 1},
                    input_schema={'required': ['n']})
    kernel, _repo, model = make_runtime(
        [tool_call_turn('step', {'n': 1}), text_turn('完成')], tools=[tool])
    run(kernel.submit('s1', 'main', {'text': '两轮'}))

    request_ids = [request.request_id for request in model.requests]
    assert len(request_ids) == 2
    assert len(set(request_ids)) == 2
    assert request_ids[0].endswith(':turn:1')
    assert request_ids[1].endswith(':turn:2')


def test_tool_invalid_arguments_rejected_without_execution():
    from asset_based_agent.technical_platform.agent_core.fakes import FakeTool
    tool = FakeTool('echo', handler=lambda args: {}, input_schema={'required': ['value']})
    kernel, repo, _model = make_runtime(
        [tool_call_turn('echo', {'wrong': 1}), text_turn('参数错了')], tools=[tool])
    run(kernel.submit('s1', 'main', {'text': 'x'}))
    entries = repo.entries('s1', 'main')
    result = next(e for e in entries if e.entry_type == 'tool_result')
    assert result.payload['status'] == 'failed'
    assert result.payload['error_code'] == 'tool.invalid_arguments'
    assert tool.calls == [], '参数校验失败不得执行工具'


def test_tool_execution_failure_feeds_back_to_model():
    from asset_based_agent.technical_platform.agent_core.fakes import FakeTool

    def boom(_args):
        raise RuntimeError('synthetic failure')

    tool = FakeTool('fragile', handler=boom)
    kernel, repo, _model = make_runtime(
        [tool_call_turn('fragile', {}), text_turn('工具失败了')], tools=[tool])
    accepted = run(kernel.submit('s1', 'main', {'text': 'x'}))
    result = next(e for e in repo.entries('s1', 'main') if e.entry_type == 'tool_result')
    assert result.payload['status'] == 'failed'
    assert result.payload['error_code'] == 'tool.failed'
    assert repo.get_operation(accepted.operation_id).status == 'completed', \
        '工具失败结果回喂模型后 operation 可正常完成'


# ------------------------------------------------------------------ 失败 / 取消 / 迟到结果

def test_model_failure_marks_operation_failed_with_error_entry():
    from asset_based_agent.technical_platform.agent_core.errors import ModelTimeout
    kernel, repo, _model = make_runtime([ModelTimeout(' synthetic timeout ')])
    accepted = run(kernel.submit('s1', 'main', {'text': '你好'}))
    operation = repo.get_operation(accepted.operation_id)
    assert operation.status == 'failed'
    assert operation.error_code == 'model.timeout'
    entries = repo.entries('s1', 'main')
    assert entries[-1].entry_type == 'error_message', '失败必须提交用户可见错误 Entry'


def test_abort_produces_aborted_operation_and_error_entry():
    from asset_based_agent.technical_platform.agent_core.contracts import ModelEvent

    def blocking_stream(_request, cancel):
        yield ModelEvent('message_start', {})
        cancel.cancel()
        yield ModelEvent('text_delta', {'text': '迟到文本'})
        yield ModelEvent('message_complete', {})

    from asset_based_agent.technical_platform.agent_core.fakes import (
        FakeModelPort,
        InMemorySessionRepo,
    )
    from asset_based_agent.technical_platform.agent_core.runtime import AgentKernel
    repo = InMemorySessionRepo()
    repo.create_session('s1', project_id='p1', owner_id='alice', title='会话')
    kernel = AgentKernel(repo=repo, model=FakeModelPort([]), tools=[])
    kernel._model = FakeModelPort.from_stream_factory(blocking_stream)
    accepted = run(kernel.submit('s1', 'main', {'text': '你好'}))
    operation = repo.get_operation(accepted.operation_id)
    assert operation.status == 'aborted'
    texts = [e for e in repo.entries('s1', 'main') if e.entry_type == 'assistant_message']
    assert texts == [], '取消后的迟到文本不得提交为 assistant Entry'
    assert repo.entries('s1', 'main')[-1].entry_type == 'error_message'


def test_same_lane_rejects_concurrent_operation():
    kernel, _repo, _model = make_runtime([text_turn('一'), text_turn('二')])

    async def hold_first():
        from asset_based_agent.technical_platform.agent_core.errors import OperationBusy
        first = await kernel.submit('s1', 'main', {'text': '一'}, wait=False)
        with pytest.raises(OperationBusy) as info:
            await kernel.submit('s1', 'main', {'text': '二'}, wait=False)
        assert info.value.code == 'agent.operation_busy'
        await kernel.wait(first.operation_id)

    run(hold_first())


def test_invalid_file_binding_does_not_leave_an_open_operation():
    kernel, repo, _model = make_runtime([text_turn('不会执行')])

    with pytest.raises(Exception):
        run(kernel.submit('s1', 'main', {
            'text': '坏绑定',
            'file_bindings': [{'file_id': '', 'sha256': ''}],
        }))

    assert repo.open_operations('s1') == []
    assert [entry.entry_type for entry in repo.entries('s1', 'main')] == []


def test_different_lanes_may_run_concurrently():
    kernel, repo, _model = make_runtime([text_turn('一'), text_turn('二')])
    repo.create_lane('s1', 'side', name='side')

    async def both():
        first = await kernel.submit('s1', 'main', {'text': '一'}, wait=False)
        second = await kernel.submit('s1', 'side', {'text': '二'}, wait=False)
        await kernel.wait(first.operation_id)
        await kernel.wait(second.operation_id)
        return first, second

    first, second = run(both())
    assert repo.get_operation(first.operation_id).status == 'completed'
    assert repo.get_operation(second.operation_id).status == 'completed'
