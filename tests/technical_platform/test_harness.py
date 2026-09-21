import json
import threading

import pytest
from test_execution import make_run


def compound(tmp_path):
    from asset_based_agent.technical_platform.execution_plan import ExecutionPlan
    from asset_based_agent.technical_platform.permissions import PermissionService
    store, run, _ = make_run(tmp_path, authorize=False)
    snapshot = json.loads(store.run(run)['snapshot'])
    first = snapshot['execution_plan']['steps'][0]
    second = {**first, 'step_id': 'second', 'dependencies': ['execute'], 'output_ref': 'second-result'}
    snapshot['execution_plan']['steps'].append(second)
    with store.connect() as db:
        db.execute('UPDATE runs SET snapshot=? WHERE id=?', (json.dumps(snapshot), run))
    PermissionService(store).authorize(run, snapshot, confirmed=True)
    return store, run, ExecutionPlan.model_validate(snapshot['execution_plan'])


def outcome(step, status='succeeded'):
    from asset_based_agent.technical_platform.tool_dispatcher import ToolOutcome
    return ToolOutcome(step_id=step.step_id, status=status,
                       passed_gates=step.acceptance_gates if status == 'succeeded' else [])


def test_harness_executes_dependencies_and_persists_each_outcome(tmp_path):
    from asset_based_agent.technical_platform.harness import execute_plan
    from asset_based_agent.technical_platform.tool_dispatcher import ToolDispatcher
    store, run, plan = compound(tmp_path)
    calls = []
    def adapter(step, dependencies, cancel):
        calls.append(step.step_id)
        assert list(dependencies) == ([] if step.step_id == 'execute' else ['execute'])
        return outcome(step)
    dispatcher = ToolDispatcher({'preflight.execute': adapter})
    assert execute_plan(store, run, plan, dispatcher, threading.Event()) == 'succeeded'
    assert calls == ['execute', 'second']
    with store.connect() as db:
        assert [r[0] for r in db.execute('SELECT state FROM execution_steps ORDER BY rowid')] == ['succeeded'] * 2
    with pytest.raises(ValueError):
        execute_plan(store, run, plan, dispatcher, threading.Event())
    assert calls == ['execute', 'second']


@pytest.mark.parametrize('stop', ['failed', 'cancelled', 'invalid'])
def test_harness_never_runs_dependent_after_failure_or_invalid_result(tmp_path, stop):
    from asset_based_agent.technical_platform.harness import execute_plan
    from asset_based_agent.technical_platform.tool_dispatcher import ToolDispatcher
    store, run, plan = compound(tmp_path)
    calls = []
    def adapter(step, dependencies, cancel):
        calls.append(step.step_id)
        if stop == 'invalid':
            return {'status': 'succeeded'}
        return outcome(step, stop)
    status = execute_plan(store, run, plan, ToolDispatcher({'preflight.execute': adapter}), threading.Event())
    assert status == ('cancelled' if stop == 'cancelled' else 'failed')
    assert calls == ['execute']


def test_harness_checks_permission_again_between_steps(tmp_path):
    from asset_based_agent.technical_platform.harness import execute_plan
    from asset_based_agent.technical_platform.permissions import PermissionService
    from asset_based_agent.technical_platform.tool_dispatcher import ToolDispatcher
    store, run, plan = compound(tmp_path)
    calls = []
    def adapter(step, dependencies, cancel):
        calls.append(step.step_id)
        PermissionService(store).revoke(run)
        return outcome(step)
    assert execute_plan(store, run, plan, ToolDispatcher({'preflight.execute': adapter}), threading.Event()) == 'failed'
    assert calls == ['execute']


def test_unknown_adapter_blocked_before_any_step(tmp_path):
    from asset_based_agent.technical_platform.harness import execute_plan
    from asset_based_agent.technical_platform.tool_dispatcher import ToolDispatcher
    store, run, plan = compound(tmp_path)
    assert execute_plan(store, run, plan, ToolDispatcher({}), threading.Event()) == 'failed'
    with store.connect() as db:
        assert db.execute('SELECT COUNT(*) FROM execution_events').fetchone()[0] == 0


@pytest.mark.parametrize('mode', ['timeout', 'missing-gate', 'cancel-late'])
def test_uncertain_or_unvalidated_results_never_continue(tmp_path, mode):
    from asset_based_agent.technical_platform.harness import execute_plan
    from asset_based_agent.technical_platform.tool_dispatcher import (
        ToolDispatcher,
        ToolOutcome,
    )
    store, run, plan = compound(tmp_path)
    calls, cancel = [], threading.Event()
    def adapter(step, dependencies, cancel):
        calls.append(step.step_id)
        if mode == 'timeout':
            raise TimeoutError('synthetic secret must not enter event log')
        if mode == 'missing-gate':
            return ToolOutcome(step_id=step.step_id, status='succeeded')
        cancel.set()
        return outcome(step)
    status = execute_plan(store, run, plan, ToolDispatcher({'preflight.execute': adapter}), cancel)
    assert status == {'timeout': 'reconciliation_required', 'missing-gate': 'failed', 'cancel-late': 'cancelled'}[mode]
    assert calls == ['execute']
    with store.connect() as db:
        assert 'synthetic secret' not in str([tuple(row) for row in db.execute('SELECT * FROM execution_events')])
    with pytest.raises(ValueError):
        execute_plan(store, run, plan, ToolDispatcher({'preflight.execute': adapter}), cancel)
    assert calls == ['execute']


def test_cancel_before_start_never_calls_adapter(tmp_path):
    from asset_based_agent.technical_platform.harness import execute_plan
    from asset_based_agent.technical_platform.tool_dispatcher import ToolDispatcher
    store, run, plan = compound(tmp_path)
    cancel = threading.Event()
    cancel.set()
    def never(*args):
        pytest.fail('cancelled task invoked tool')
    assert execute_plan(store, run, plan, ToolDispatcher({'preflight.execute': never}), cancel) == 'cancelled'
