"""S1 生命周期安全：终态兜底 / 真实 Resume / 内存运行态清理（先红后绿）。

验收锚（总任务书 S1）：
- begin_operation 之后任何异常路径都必须把 operation 收束到终态；
- resume 使用 ordinal = max(existing)+1，保留历史 unknown Turn；
- 后台 Task 完成后从 kernel._tasks 清除。
"""
import asyncio
import sqlite3

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


def make_kernel(*, scripts=(), tools=(), repo=None, context_builder=None,
                tool_resolver=None, stream_factory=None):
    from asset_based_agent.technical_platform.agent_core.fakes import (
        FakeModelPort,
        InMemorySessionRepo,
    )
    from asset_based_agent.technical_platform.agent_core.runtime import (
        AgentKernel,
    )
    repo = repo or InMemorySessionRepo()
    if stream_factory is not None:
        model = FakeModelPort.from_stream_factory(stream_factory)
    else:
        model = FakeModelPort(list(scripts))
    kernel = AgentKernel(repo=repo, model=model, tools=list(tools),
                         context_builder=context_builder,
                         tool_resolver=tool_resolver)
    repo.create_session('s1', project_id='p1', owner_id='alice', title='会话')
    return kernel, repo


def sqlite_repo(tmp_path):
    from asset_based_agent.technical_platform.sessions.sqlite_repository import (
        SQLiteSessionRepo,
    )
    from asset_based_agent.technical_platform.store import PlatformStore
    PlatformStore(tmp_path / 'db.sqlite', 'alice')
    return SQLiteSessionRepo(tmp_path / 'db.sqlite', 'alice')


def pinned_resolver():
    class _Resolver:
        def resolve_pinned(self, snapshot):
            return []

        def resolve_for_operation(self, skill_ids=None):
            return [], None

    return _Resolver()


# ------------------------------------------------------------------ S1-01 终态兜底

def test_context_builder_runtime_error_terminalizes_operation():
    class BrokenContextBuilder:
        def build(self, **kwargs):
            raise RuntimeError('boom')

    kernel, repo = make_kernel(context_builder=BrokenContextBuilder())
    accepted = run(kernel.submit('s1', 'main', {'text': '问'}))
    assert repo.open_operations('s1') == [], '异常后 operation 不得停留 open'
    record = repo.get_operation(accepted.operation_id)
    assert record.status in {'completed', 'failed', 'aborted', 'unknown'}
    assert record.status == 'failed'
    assert record.error_code == 'agent.internal_error'


def test_begin_turn_sqlite_error_terminalizes_operation():
    kernel, repo = make_kernel(scripts=[text_turn('不应到达')])

    def boom(*_args, **_kwargs):
        raise sqlite3.OperationalError('database is locked')

    repo.begin_turn = boom
    accepted = run(kernel.submit('s1', 'main', {'text': '问'}))
    assert repo.open_operations('s1') == []
    record = repo.get_operation(accepted.operation_id)
    assert record.status == 'failed'
    assert record.error_code == 'agent.internal_error'


def test_record_event_failure_does_not_leave_operation_open():
    kernel, repo = make_kernel(scripts=[text_turn('好')])
    original = repo.record_event

    def flaky(session_id, lane_id, event_type, **kwargs):
        if event_type in ('operation_started', 'turn_started',
                          'message_committed', 'turn_completed'):
            raise RuntimeError('disk full')
        return original(session_id, lane_id, event_type, **kwargs)

    repo.record_event = flaky
    accepted = run(kernel.submit('s1', 'main', {'text': '问'}))
    assert repo.open_operations('s1') == []
    assert repo.get_operation(accepted.operation_id).status == 'completed'


def test_unexpected_exception_writes_user_visible_error_entry():
    class LeakyContextBuilder:
        def build(self, **kwargs):
            raise RuntimeError('C:\\private\\path token=secret-value')

    kernel, repo = make_kernel(context_builder=LeakyContextBuilder())
    accepted = run(kernel.submit('s1', 'main', {'text': '问'}))
    errors = [e for e in repo.entries('s1', 'main')
              if e.entry_type == 'error_message'
              and e.operation_id == accepted.operation_id]
    assert errors, '未归类异常必须写入用户可见错误 Entry'
    text = errors[-1].payload.get('text', '')
    assert text.strip(), '错误 Entry 不得为空'
    assert 'secret' not in text and 'C:\\' not in text, \
        '错误 Entry 不得泄露路径 / token / 堆栈'


def test_worker_exit_implies_no_open_operation():
    def factory(_request, _cancel):
        raise ValueError('unexpected worker crash')
        yield  # pragma: no cover - 标记为生成器

    kernel, repo = make_kernel(stream_factory=factory)

    async def main():
        accepted = await kernel.submit('s1', 'main', {'text': '问'},
                                       wait=False)
        await kernel.wait(accepted.operation_id)
        return accepted

    accepted = run(main())
    assert repo.open_operations('s1') == [], \
        'worker 退出后不得残留 open operation'
    record = repo.get_operation(accepted.operation_id)
    assert record.status in {'completed', 'failed', 'aborted', 'unknown'}


# ------------------------------------------------------------------ S1-02 真实 Resume

def _interrupted_operation_with_turn(repo):
    operation = repo.begin_operation('s1', 'main', user_text='问',
                                     request_id='r1')
    repo.begin_turn(operation.id, 1, input_context_sha256='x',
                    model_request_id='r1:turn:1')
    repo.interrupt_operation(operation.id, code='agent.interrupted',
                             summary='进程中断')
    return operation


def test_resume_after_started_turn_uses_next_ordinal():
    kernel, repo = make_kernel(scripts=[text_turn('恢复后的回答')],
                               tool_resolver=pinned_resolver())
    operation = _interrupted_operation_with_turn(repo)
    run(kernel.resume(operation.id))
    turns = repo.turns(operation.id)
    assert [t.ordinal for t in turns] == [1, 2], \
        '恢复必须新建 ordinal=max(existing)+1 的 Turn'
    assert turns[1].status == 'completed'
    assert repo.get_operation(operation.id).status == 'completed'


def test_resume_keeps_original_unknown_turn():
    kernel, repo = make_kernel(scripts=[text_turn('恢复后的回答')],
                               tool_resolver=pinned_resolver())
    operation = _interrupted_operation_with_turn(repo)
    run(kernel.resume(operation.id))
    first = repo.turns(operation.id)[0]
    assert first.ordinal == 1
    assert first.status == 'unknown', '历史 unknown Turn 不得删除或覆盖'
    assert first.error_code == 'agent.interrupted'


def test_resume_does_not_violate_unique_operation_ordinal(tmp_path):
    repo = sqlite_repo(tmp_path)
    kernel, repo = make_kernel(scripts=[text_turn('恢复后的回答')], repo=repo,
                               tool_resolver=pinned_resolver())
    operation = _interrupted_operation_with_turn(repo)
    run(kernel.resume(operation.id))  # 不得抛 IntegrityError
    ordinals = [t.ordinal for t in repo.turns(operation.id)]
    assert ordinals == [1, 2]
    assert len(set(ordinals)) == len(ordinals)


def test_resume_after_tool_call_requires_recovery_policy():
    from asset_based_agent.technical_platform.agent_core.errors import (
        ToolUnknownOutcome,
    )
    kernel, repo = make_kernel(scripts=[text_turn('不应到达')],
                               tool_resolver=pinned_resolver())
    operation = repo.begin_operation('s1', 'main', user_text='问',
                                     request_id='r1')
    turn_id = repo.begin_turn(operation.id, 1, input_context_sha256='x',
                              model_request_id='r1:turn:1')
    repo.begin_tool_call(operation.id, turn_id, name='generate_report',
                         arguments={}, risk='local_create',
                         idempotency_key='k1')
    repo.interrupt_operation(operation.id, code='agent.interrupted',
                             summary='进程中断')
    with pytest.raises(ToolUnknownOutcome):
        run(kernel.resume(operation.id))
    record = repo.get_operation(operation.id)
    assert record.status in {'completed', 'failed', 'aborted', 'unknown'}
    assert record.status != 'running'
    assert record.error_code == 'tool.unknown_outcome'


# ------------------------------------------------------------------ S1-05 内存运行态

def test_completed_background_task_removed_from_kernel_task_registry():
    kernel, repo = make_kernel(scripts=[text_turn('好')])

    async def main():
        accepted = await kernel.submit('s1', 'main', {'text': '问'},
                                       wait=False)
        await kernel.wait(accepted.operation_id)
        await asyncio.sleep(0)  # 让 done callback 完成清理
        return accepted

    accepted = run(main())
    assert repo.get_operation(accepted.operation_id).status == 'completed'
    assert accepted.operation_id not in kernel._tasks, \
        '已完成 Task 不得永久保留在 kernel._tasks'
