"""S2-02 Tool Recovery Policy：中断工具的恢复策略（先红后绿）。

断言核心：非幂等写操作绝不自动再次执行。
"""
import asyncio

import pytest


def run(coro):
    return asyncio.run(coro)


def text_turn(text):
    from asset_based_agent.technical_platform.agent_core.contracts import (
        ModelEvent,
    )
    return [ModelEvent('message_start', {}),
            ModelEvent('text_delta', {'text': text}),
            ModelEvent('message_complete', {})]


def make_stack(tools, *, scripts=None):
    from asset_based_agent.technical_platform.agent_core.fakes import (
        FakeModelPort,
        InMemorySessionRepo,
    )
    from asset_based_agent.technical_platform.agent_core.runtime import (
        AgentKernel,
    )

    class _Resolver:
        def resolve_pinned(self, snapshot):
            return list(tools)

        def resolve_for_operation(self, skill_ids=None):
            return list(tools), None

    repo = InMemorySessionRepo()
    repo.create_session('s1', project_id='p1', owner_id='alice', title='会话')
    kernel = AgentKernel(repo=repo,
                         model=FakeModelPort(list(scripts or [text_turn('好')])),
                         tools=list(tools), tool_resolver=_Resolver())
    return kernel, repo


def interrupted_op_with_tool_call(repo, name, risk):
    operation = repo.begin_operation('s1', 'main', user_text='问',
                                     request_id='r1')
    turn_id = repo.begin_turn(operation.id, 1, input_context_sha256='x',
                              model_request_id='r1:turn:1')
    repo.begin_tool_call(operation.id, turn_id, name=name, arguments={},
                         risk=risk, idempotency_key=f'k-{name}')
    repo.interrupt_operation(operation.id, code='agent.interrupted',
                             summary='进程中断')
    return operation


def test_read_tool_interrupted_resume_replays_safely():
    from asset_based_agent.technical_platform.agent_core.fakes import FakeTool
    tool = FakeTool('read_project_file', handler=lambda args: '内容',
                    risk='local_readonly')
    kernel, repo = make_stack([tool])
    operation = interrupted_op_with_tool_call(repo, 'read_project_file',
                                              'local_readonly')
    run(kernel.resume(operation.id))
    record = repo.get_operation(operation.id)
    assert record.status == 'completed', '只读工具中断后应可安全恢复'
    assert [t.ordinal for t in repo.turns(operation.id)] == [1, 2]


def test_idempotent_business_run_interrupted_resume_allowed():
    from asset_based_agent.technical_platform.agent_core.fakes import FakeTool
    tool = FakeTool('execute_skill_plan', handler=lambda args: 'ok',
                    risk='process', recovery_policy='idempotent_retry')
    kernel, repo = make_stack([tool])
    operation = interrupted_op_with_tool_call(repo, 'execute_skill_plan',
                                              'process')
    run(kernel.resume(operation.id))
    assert repo.get_operation(operation.id).status == 'completed'


def test_upload_interrupted_requires_manual_reconcile():
    from asset_based_agent.technical_platform.agent_core.errors import (
        ToolUnknownOutcome,
    )
    from asset_based_agent.technical_platform.agent_core.fakes import FakeTool
    tool = FakeTool('browser_upload', handler=lambda args: 'ok',
                    risk='external_upload')
    kernel, repo = make_stack([tool])
    operation = interrupted_op_with_tool_call(repo, 'browser_upload',
                                              'external_upload')
    with pytest.raises(ToolUnknownOutcome):
        run(kernel.resume(operation.id))
    record = repo.get_operation(operation.id)
    assert record.status == 'failed'
    assert record.error_code == 'tool.unknown_outcome'
    assert tool.calls == [], '上传类工具绝不自动再次执行'


def test_original_modify_interrupted_never_retried():
    from asset_based_agent.technical_platform.agent_core.errors import (
        ToolUnknownOutcome,
    )
    from asset_based_agent.technical_platform.agent_core.fakes import FakeTool
    tool = FakeTool('modify_original', handler=lambda args: 'ok',
                    risk='original_modify')
    kernel, repo = make_stack([tool])
    operation = interrupted_op_with_tool_call(repo, 'modify_original',
                                              'original_modify')
    with pytest.raises(ToolUnknownOutcome):
        run(kernel.resume(operation.id))
    assert repo.get_operation(operation.id).status == 'failed'
    assert tool.calls == [], '原件修改绝不自动再次执行'
