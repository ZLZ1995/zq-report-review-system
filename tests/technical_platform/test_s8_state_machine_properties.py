"""S8-05 状态机 Property Tests（客户端侧五套）。

对 Agent Operation / Agent Turn / ToolCall / Browser Task / Workflow
定义允许边并验证三条不变量：

1. 任何入口执行完成后，不得出现无 owner 的 running；
2. 不得存在不可达状态（观测到的状态必须 ∈ 允许集合）；
3. terminal 不能回到 running（除明确 resume：仅 unknown → running）。
"""
from __future__ import annotations

import pytest

from asset_based_agent.technical_platform.sessions.models import (
    OPEN_STATUSES,
    OPERATION_STATUSES,
    TOOL_CALL_OPEN_STATUSES,
    TURN_OPEN_STATUSES,
)

TURN_TERMINAL_STATUSES = frozenset({'succeeded', 'failed', 'cancelled', 'unknown'})
TOOL_CALL_TERMINAL_STATUSES = frozenset(
    {'succeeded', 'failed', 'aborted', 'unknown'})
OPERATION_TERMINAL_STATUSES = OPERATION_STATUSES - OPEN_STATUSES


def _sqlite_repo(tmp_path):
    from asset_based_agent.technical_platform.sessions.sqlite_repository import (
        SQLiteSessionRepo,
    )
    from asset_based_agent.technical_platform.store import PlatformStore
    PlatformStore(tmp_path / 'db.sqlite', 'alice')
    repo = SQLiteSessionRepo(tmp_path / 'db.sqlite', 'alice')
    repo.create_session('s1', project_id='p1', owner_id='alice', title='会话')
    return repo


def _assert_operation_invariants(repo, operation_id):
    operation = repo.get_operation(operation_id)
    assert operation.status in OPERATION_STATUSES, \
        f'不可达状态: {operation.status}'
    if operation.status in OPEN_STATUSES:
        # 不变量 1：活动中的 operation 必须有执行 owner
        assert operation.executor_id, \
            f'open 状态 {operation.status} 不得无 owner'
    else:
        assert operation.finished_at is not None, '终态必须有完成时间'


# ------------------------------------------------------- Agent Operation

def test_operation_happy_path_and_terminal_guard(tmp_path):
    repo = _sqlite_repo(tmp_path)
    operation = repo.begin_operation(
        's1', 'main', user_text='问', request_id='r1',
        executor_id='proc-a', lease_seconds=300)
    _assert_operation_invariants(repo, operation.id)

    repo.complete_operation(operation.id, assistant_entry_id='e1', turn_id=None)
    _assert_operation_invariants(repo, operation.id)
    assert repo.get_operation(operation.id).status == 'completed'

    # 不变量 3：终态不得回到 running（resume 仅允许 unknown）
    with pytest.raises(ValueError):
        repo.resume_operation(operation.id)
    _assert_operation_invariants(repo, operation.id)


def test_operation_explicit_resume_only_from_unknown(tmp_path):
    repo = _sqlite_repo(tmp_path)
    operation = repo.begin_operation(
        's1', 'main', user_text='问', request_id='r2',
        executor_id='proc-a', lease_seconds=300)
    repo.interrupt_operation(operation.id, code='crash', summary='进程崩溃')
    assert repo.get_operation(operation.id).status == 'unknown'

    # 明确 resume：unknown → running，重新获得 owner
    repo.resume_operation(operation.id)
    resumed = repo.get_operation(operation.id)
    assert resumed.status == 'running'
    repo.fail_operation(operation.id, code='boom', summary='失败', turn_id=None)
    _assert_operation_invariants(repo, operation.id)
    assert repo.get_operation(operation.id).status == 'failed'
    with pytest.raises(ValueError):
        repo.resume_operation(operation.id)


# ------------------------------------------------------------ Agent Turn

def test_turn_states_stay_within_allowed_edges(tmp_path):
    repo = _sqlite_repo(tmp_path)
    operation = repo.begin_operation(
        's1', 'main', user_text='问', request_id='r3',
        executor_id='proc-a', lease_seconds=300)
    turn_id = repo.begin_turn(operation.id, 1, input_context_sha256='a' * 64)
    turn = repo.turns(operation.id)[0]
    assert turn.status in TURN_OPEN_STATUSES, f'turn 初始状态非法: {turn.status}'
    assert turn.finished_at is None

    repo.finish_turn(turn_id, 'succeeded',
                     usage={'input_tokens': 10})
    turn = repo.turns(operation.id)[0]
    assert turn.status in TURN_TERMINAL_STATUSES
    assert turn.finished_at is not None


def test_turn_open_statuses_all_reachable_and_closed_by_interrupt(tmp_path):
    repo = _sqlite_repo(tmp_path)
    operation = repo.begin_operation(
        's1', 'main', user_text='问', request_id='r4',
        executor_id='proc-a', lease_seconds=300)
    repo.begin_turn(operation.id, 1, input_context_sha256='b' * 64)
    repo.interrupt_operation(operation.id, code='crash', summary='崩溃')
    turn = repo.turns(operation.id)[0]
    assert turn.status == 'unknown', '中断必须收束 open turn'
    assert turn.finished_at is not None


# -------------------------------------------------------------- ToolCall

def test_tool_call_result_statuses_and_idempotency_guard(tmp_path):
    from asset_based_agent.technical_platform.agent_core.contracts import (
        TOOL_RESULT_STATUSES,
    )
    repo = _sqlite_repo(tmp_path)
    operation = repo.begin_operation(
        's1', 'main', user_text='问', request_id='r5',
        executor_id='proc-a', lease_seconds=300)
    turn_id = repo.begin_turn(operation.id, 1, input_context_sha256='c' * 64)

    for index, status in enumerate(sorted(TOOL_RESULT_STATUSES)):
        call_id = repo.begin_tool_call(
            operation.id, turn_id, name='tool', arguments={'i': index},
            risk='read', idempotency_key=f'k-{index}')
        call = repo.tool_calls(operation.id)[-1]
        assert call.status in TOOL_CALL_OPEN_STATUSES
        repo.finish_tool_call(call_id, status)
        call = repo.tool_calls(operation.id)[-1]
        assert call.status in TOOL_CALL_TERMINAL_STATUSES
        assert call.finished_at is not None

    # 同一 idempotency_key 不得产生第二个 call（幂等边）
    with pytest.raises(ValueError, match='idempotency_key'):
        repo.begin_tool_call(
            operation.id, turn_id, name='tool', arguments={'i': 0},
            risk='read', idempotency_key='k-0')


def test_tool_result_contract_rejects_unreachable_status():
    from asset_based_agent.technical_platform.agent_core.contracts import (
        ToolResult,
    )
    with pytest.raises(ValueError):
        ToolResult(status='half-done')  # 不在 TOOL_RESULT_STATUSES 内
    for status in ('succeeded', 'failed', 'aborted', 'unknown'):
        ToolResult(status=status)


# ---------------------------------------------------------- Browser Task

def _leases_setup():
    from threading import Event
    from types import SimpleNamespace

    from asset_based_agent.technical_platform.browser_task_leases import (
        BrowserTaskLeases,
    )
    from asset_based_agent.technical_platform.task_manager import (
        TaskBinding,
        TaskManager,
    )
    page = object()
    session = SimpleNamespace(owner='alice', owns_page=lambda p: p is page)
    manager = TaskManager()
    worker = SimpleNamespace(cancel=Event(), isRunning=lambda: True)
    binding = TaskBinding('alice', 'p', 's', 't')
    manager.register(binding, worker)
    leases = BrowserTaskLeases(session, manager)
    leases.register(page)
    return leases, page, binding, worker


def test_browser_task_lease_terminal_never_revives():
    leases, page, binding, worker = _leases_setup()
    lease = leases.acquire(page, binding, worker, confirmed=True)
    assert leases.valid(lease), 'acquire 后 lease 必须有效（running 有 owner）'

    leases.release(lease)
    assert not leases.valid(lease), 'release 是终态：不得重新生效'
    renewed = leases.acquire(page, binding, worker, confirmed=True)
    assert leases.valid(renewed) and not leases.valid(lease)

    leases.close()
    assert not leases.valid(renewed), 'close 后一切 lease 必须失效'
    with pytest.raises(PermissionError):
        leases.acquire(page, binding, worker, confirmed=True)


def test_browser_task_lease_requires_owner_and_consent():
    from dataclasses import replace

    leases, page, binding, worker = _leases_setup()
    # 不变量 1 的反面：无确认 / 非 owner 一律不得进入 running
    with pytest.raises(PermissionError):
        leases.acquire(page, binding, worker, confirmed=False)
    with pytest.raises(PermissionError):
        leases.acquire(page, replace(binding, owner='bob'), worker,
                       confirmed=True)
    worker.cancel.set()  # worker 不再存活
    with pytest.raises(PermissionError):
        leases.acquire(page, binding, worker, confirmed=True)


# -------------------------------------------------------------- Workflow

def _make_envelope():
    from asset_based_agent.technical_platform.turn_scope_policy import (
        resolve_scope,
    )
    files = [{'id': 'f1', 'name': '审核报告.docx', 'sha256': 'a' * 64}]
    return resolve_scope(
        owner='alice', project_id='p1', session_id='s1',
        raw_user_text='审审核报告.docx', selected_ids=['f1'],
        available_files=files, active_model_id='model-a',
        permission_mode='risk', clock=None)


def _compiled(envelope):
    from asset_based_agent.technical_platform.turn_context import envelope_hash
    from asset_based_agent.technical_platform.workflow_compiler import (
        compile_plan,
    )
    return compile_plan({
        'plan_id': 'plan-1', 'revision': 1,
        'envelope_hash': envelope_hash(envelope),
        'revision_reason': 'initial',
        'nodes': [
            {'node_id': 's1', 'type': 'model_call', 'inputs': [],
             'depends_on': [],
             'config': {'client_job_id': 'job-1', 'resource': 'model:default'}},
            {'node_id': 's2', 'type': 'run_skill',
             'inputs': [{'kind': 'attachment', 'ref': 'f1'}],
             'depends_on': ['s1'],
             'config': {'skill_id': 'report.review', 'resource': 'workbook:f1'}},
            {'node_id': 'd1', 'type': 'deliver',
             'inputs': [{'kind': 'node_output', 'ref': 's2'}],
             'depends_on': ['s2'], 'config': {}},
        ]}, envelope=envelope, allowed_tools=('report.review',))


def _recording_executors(calls, failures=None):
    failures = failures or {}

    def factory(node_type):
        def execute(node, inputs):
            calls.append(node.node_id)
            error = failures.get(node.node_id)
            if error is not None:
                raise error('失败')
            return {'output': node.node_id + '-result'}
        return execute

    return {node_type: factory(node_type)
            for node_type in ('model_call', 'run_skill', 'deliver')}


WORKFLOW_TERMINAL_STATES = frozenset({'succeeded', 'failed', 'cancelled'})


def test_workflow_terminal_state_is_final_and_replay_safe():
    from asset_based_agent.technical_platform.workflow_journal import (
        WorkflowJournal,
    )
    from asset_based_agent.technical_platform.workflow_runtime import (
        WorkflowRuntime,
    )
    compiled = _compiled(_make_envelope())
    calls = []
    journal = WorkflowJournal()
    runtime = WorkflowRuntime(journal, _recording_executors(calls))

    result = runtime.run(compiled, run_id='run-1')
    assert result.state in WORKFLOW_TERMINAL_STATES
    assert result.state == 'succeeded'
    assert sorted(result.committed) == ['d1', 's1', 's2']
    assert sorted(calls) == ['d1', 's1', 's2']

    # 不变量 3：终态后重放同一 run_id 不得重新执行任何节点
    replay = runtime.run(compiled, run_id='run-1')
    assert replay.state == 'succeeded'
    assert sorted(calls) == ['d1', 's1', 's2'], '终态 run 不得重新执行节点'


def test_workflow_failure_state_is_terminal_and_partial_replay_resumes():
    from asset_based_agent.technical_platform.workflow_journal import (
        WorkflowJournal,
    )
    from asset_based_agent.technical_platform.workflow_runtime import (
        WorkflowRuntime,
    )
    compiled = _compiled(_make_envelope())
    calls = []
    journal = WorkflowJournal()
    runtime = WorkflowRuntime(
        journal, _recording_executors(calls, failures={'s2': ValueError}))

    result = runtime.run(compiled, run_id='run-2')
    assert result.state == 'failed'
    assert 's1' in result.committed and 's2' not in result.committed

    # 恢复执行：已 committed 的 s1 不得重跑（无重复副作用）
    fixed = WorkflowRuntime(journal, _recording_executors(calls))
    recovered = fixed.run(compiled, run_id='run-2')
    assert recovered.state == 'succeeded'
    assert calls.count('s1') == 1, '已提交节点不得重复执行'
