"""G07：Workflow Harness v2 — 调度、资源锁、取消、恢复、幂等、对账。

验收：进程中断恢复不重复扣费；同一资源无并发写；取消后无副作用；
unknown 进入对账不盲目重放；既有任务类型兼容（编译产物直接可跑）。
"""
import threading

import pytest


def make_envelope():
    from asset_based_agent.technical_platform.turn_scope_policy import resolve_scope
    files = [{'id': 'f1', 'name': '审核报告.docx', 'sha256': 'a' * 64}]
    return resolve_scope(
        owner='alice', project_id='p1', session_id='s1',
        raw_user_text='审审核报告.docx', selected_ids=['f1'],
        available_files=files, active_model_id='model-a', permission_mode='risk',
        clock=None)


def compiled_two_steps(envelope):
    from asset_based_agent.technical_platform.turn_context import envelope_hash
    from asset_based_agent.technical_platform.workflow_compiler import compile_plan
    return compile_plan({
        'plan_id': 'plan-1', 'revision': 1, 'envelope_hash': envelope_hash(envelope),
        'revision_reason': 'initial',
        'nodes': [
            {'node_id': 's1', 'type': 'model_call', 'inputs': [], 'depends_on': [],
             'config': {'client_job_id': 'job-1', 'resource': 'model:default'}},
            {'node_id': 's2', 'type': 'run_skill',
             'inputs': [{'kind': 'attachment', 'ref': 'f1'}], 'depends_on': ['s1'],
             'config': {'skill_id': 'report.review', 'resource': 'workbook:f1'}},
            {'node_id': 'd1', 'type': 'deliver',
             'inputs': [{'kind': 'node_output', 'ref': 's2'}], 'depends_on': ['s2'],
             'config': {}},
        ]}, envelope=envelope, allowed_tools=('report.review',))


def make_runtime(executors, journal=None, **kwargs):
    from asset_based_agent.technical_platform.workflow_journal import WorkflowJournal
    from asset_based_agent.technical_platform.workflow_runtime import WorkflowRuntime
    journal = journal or WorkflowJournal()
    return WorkflowRuntime(journal, executors, **kwargs), journal


def recording_executors(calls, failures=None):
    failures = failures or {}

    def factory(node_type):
        def execute(node, inputs):
            calls.append(node.node_id)
            error = failures.get(node.node_id)
            if error is not None:
                if isinstance(error, list) and error:
                    raise error.pop(0)
                if isinstance(error, type) and issubclass(error, BaseException):
                    raise error('失败')
                if isinstance(error, BaseException):
                    raise error
            return {'output': node.node_id + '-result'}
        return execute

    return {node_type: factory(node_type)
            for node_type in ('model_call', 'run_skill', 'deliver')}


# --- Journal ---

def test_journal_appends_ordered_events():
    from asset_based_agent.technical_platform.workflow_journal import WorkflowJournal
    journal = WorkflowJournal()
    journal.append(run_id='r1', node_id=None, type='run_created', at='t0')
    journal.append(run_id='r1', node_id='s1', type='node_claimed', at='t1')
    events = journal.events('r1')
    assert [event.seq for event in events] == [1, 2]
    assert events[1].type == 'node_claimed'


def test_journal_recovers_terminal_state_after_crash(tmp_path):
    from asset_based_agent.technical_platform.workflow_journal import WorkflowJournal
    path = tmp_path / 'journal.jsonl'
    journal = WorkflowJournal(path)
    journal.append(run_id='r1', node_id=None, type='run_created', at='t0')
    journal.append(run_id='r1', node_id='s1', type='node_result_committed', at='t1')
    recovered = WorkflowJournal(path)
    assert recovered.committed_nodes('r1') == {'s1'}
    assert recovered.terminal_state('r1') is None


def test_journal_event_rejects_unknown_type():
    from asset_based_agent.technical_platform.workflow_journal import WorkflowJournal
    with pytest.raises(ValueError):
        WorkflowJournal().append(run_id='r1', node_id=None, type='explode', at='t0')


# --- 资源锁 ---

def test_resource_pool_blocks_concurrent_writer():
    from asset_based_agent.technical_platform.workflow_scheduler import ResourcePool
    pool = ResourcePool()
    assert pool.try_acquire('workbook:f1', 'r1') is True
    assert pool.try_acquire('workbook:f1', 'r2') is False
    pool.release('workbook:f1', 'r1')
    assert pool.try_acquire('workbook:f1', 'r2') is True


# --- Runtime ---

def test_run_commits_all_nodes_and_terminates():
    envelope = make_envelope()
    calls = []
    runtime, journal = make_runtime(recording_executors(calls))
    result = runtime.run(compiled_two_steps(envelope), run_id='r1')
    assert result.state == 'succeeded'
    assert calls == ['s1', 's2', 'd1']
    types = [event.type for event in journal.events('r1')]
    assert types[0] == 'run_created' and types[-1] == 'run_terminal'
    assert 'node_result_committed' in types


def test_cancel_stops_side_effects_and_releases_locks():
    envelope = make_envelope()
    cancel = threading.Event()
    calls = []

    def cancelling(node, inputs):
        calls.append(node.node_id)
        cancel.set()
        return {'output': 'partial'}

    runtime, journal = make_runtime({**recording_executors(calls),
                                     'model_call': cancelling})
    result = runtime.run(compiled_two_steps(envelope), run_id='r1', cancel=cancel)
    assert result.state == 'cancelled'
    assert calls == ['s1']
    assert journal.terminal_state('r1') == 'cancelled'


def test_crash_resume_skips_committed_nodes_no_double_charge():
    envelope = make_envelope()
    calls = []

    class Crash(Exception):
        pass

    failures = {'s2': [Crash('进程中断')]}
    runtime, journal = make_runtime(recording_executors(calls, failures))
    with pytest.raises(Crash):
        runtime.run(compiled_two_steps(envelope), run_id='r1')
    assert calls == ['s1', 's2']

    resumed_calls = []
    runtime2, _journal2 = make_runtime(recording_executors(resumed_calls),
                                       journal=journal)
    result = runtime2.run(compiled_two_steps(envelope), run_id='r1')
    assert result.state == 'succeeded'
    assert resumed_calls == ['s2', 'd1']  # s1（模型调用）不重放，不重复扣费


def test_retry_then_success_with_backoff_event():
    envelope = make_envelope()
    calls = []
    failures = {'s2': [TimeoutError('超时')]}
    sleeps = []
    runtime, journal = make_runtime(recording_executors(calls, failures),
                                    sleeper=sleeps.append, max_attempts=2)
    result = runtime.run(compiled_two_steps(envelope), run_id='r1')
    assert result.state == 'succeeded'
    assert calls == ['s1', 's2', 's2', 'd1']
    assert any(event.type == 'node_retrying' for event in journal.events('r1'))


def test_non_retryable_failure_terminates_run():
    envelope = make_envelope()
    calls = []
    failures = {'s2': ValueError('契约不满足')}
    runtime, journal = make_runtime(recording_executors(calls, failures),
                                    max_attempts=3)
    result = runtime.run(compiled_two_steps(envelope), run_id='r1')
    assert result.state == 'failed'
    assert calls == ['s1', 's2']
    assert journal.terminal_state('r1') == 'failed'


def test_waiting_event_when_resource_busy():
    envelope = make_envelope()
    calls = []
    runtime, journal = make_runtime(recording_executors(calls))
    from asset_based_agent.technical_platform.workflow_scheduler import ResourcePool
    pool = ResourcePool()
    pool.try_acquire('workbook:f1', 'other-run')
    waits = []

    def release_after_two(_seconds):
        waits.append(1)
        if len(waits) == 2:
            pool.release('workbook:f1', 'other-run')

    runtime._pool = pool
    result = runtime.run(compiled_two_steps(envelope), run_id='r1',
                         sleeper=release_after_two)
    assert result.state == 'succeeded'
    assert any(event.type == 'node_waiting_resource'
               for event in journal.events('r1'))


def test_cache_key_binds_plan_skill_and_permission():
    from asset_based_agent.technical_platform.workflow_runtime import node_cache_key
    envelope = make_envelope()
    compiled = compiled_two_steps(envelope)
    step = compiled.steps[1]
    first = node_cache_key(compiled, step, permission_snapshot='risk')
    assert first == node_cache_key(compiled, step, permission_snapshot='risk')
    assert first != node_cache_key(compiled, step, permission_snapshot='auto')


# --- 对账 ---

def test_unknown_model_call_reconciles_by_client_job_id():
    from asset_based_agent.technical_platform.workflow_reconciliation import (
        reconcile_unknown,
    )
    lookup = {'job-1': 'charged'}
    decision = reconcile_unknown('model_call', 'job-1', remote_lookup=lookup.get)
    assert decision.outcome == 'settled_charged'


def test_unknown_model_call_not_found_goes_manual():
    from asset_based_agent.technical_platform.workflow_reconciliation import (
        reconcile_unknown,
    )
    decision = reconcile_unknown('model_call', 'job-9', remote_lookup=lambda _i: None)
    assert decision.outcome == 'manual_review'


def test_unknown_write_action_never_replays():
    from asset_based_agent.technical_platform.workflow_reconciliation import (
        reconcile_unknown,
    )
    for kind in ('office_write', 'browser_action', 'deliver'):
        decision = reconcile_unknown(kind, 'x', remote_lookup=lambda _i: None)
        assert decision.outcome == 'manual_review'
