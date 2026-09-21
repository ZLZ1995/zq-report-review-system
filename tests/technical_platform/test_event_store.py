import json
from concurrent.futures import ThreadPoolExecutor

import pytest
from test_execution import make_run


def prepared(tmp_path):
    from asset_based_agent.technical_platform.event_store import ExecutionStore
    from asset_based_agent.technical_platform.execution_plan import ExecutionPlan
    store, run, _ = make_run(tmp_path)
    store.claim_run(run)
    plan = ExecutionPlan.model_validate(json.loads(store.run(run)['snapshot'])['execution_plan'])
    events = ExecutionStore(store)
    events.register(plan)
    return store, run, plan, events


def test_registration_is_idempotent_and_rejects_changed_plan(tmp_path):
    store, run, plan, events = prepared(tmp_path)
    events.register(plan)
    changed = plan.model_dump()
    changed['revision'] = 2
    with pytest.raises(PermissionError):
        events.register(type(plan).model_validate(changed))
    with store.connect() as db:
        assert db.execute('SELECT COUNT(*) FROM execution_steps').fetchone()[0] == 1
    assert events.events(run) == []


def test_step_claim_is_atomic_and_never_reclaims_running_step(tmp_path):
    _, run, _, events = prepared(tmp_path)
    def claim(_):
        try:
            return events.claim(run, 'execute')
        except ValueError:
            return None
    with ThreadPoolExecutor(max_workers=2) as pool:
        claims = list(pool.map(claim, range(2)))
    assert sum(value is not None for value in claims) == 1
    assert [event['kind'] for event in events.events(run)] == ['running']
    with pytest.raises(ValueError):
        events.claim(run, 'execute')


def test_terminal_checkpoint_requires_claim_and_actual_run_terminal(tmp_path):
    store, run, _, events = prepared(tmp_path)
    claim = events.claim(run, 'execute')
    with pytest.raises(ValueError):
        events.record_run_terminal(run, claim)
    store.transition(run, 'validating', 'synthetic')
    store.transition(run, 'succeeded', 'synthetic')
    with pytest.raises(PermissionError):
        events.record_run_terminal(run, 'wrong-token')
    events.record_run_terminal(run, claim)
    events.record_run_terminal(run, claim)
    rows = events.events(run)
    assert [(r['sequence'], r['kind']) for r in rows] == [(1, 'running'), (2, 'succeeded')]
    assert [r['sequence'] for r in events.events(run, after=1)] == [2]
    with store.connect() as db:
        step = db.execute('SELECT * FROM execution_steps WHERE run=?', (run,)).fetchone()
        assert step['state'] == 'succeeded' and step['attempt'] == 1


def test_event_access_is_owner_scoped(tmp_path):
    from asset_based_agent.technical_platform.event_store import ExecutionStore
    from asset_based_agent.technical_platform.store import PlatformStore
    store, run, plan, _ = prepared(tmp_path)
    other = ExecutionStore(PlatformStore(store.path, 'bob'))
    for operation in [lambda: other.register(plan), lambda: other.claim(run, 'execute'),
                      lambda: other.events(run), lambda: other.record_run_terminal(run, 'token')]:
        with pytest.raises(PermissionError):
            operation()


def test_registration_accepts_earlier_plan_without_optional_step_metadata(tmp_path):
    from asset_based_agent.technical_platform.event_store import ExecutionStore
    from asset_based_agent.technical_platform.execution_plan import ExecutionPlan

    def legacy(snapshot):
        for step in snapshot['execution_plan']['steps']:
            for key in ('goal', 'constraints', 'target_inputs', 'reference_inputs'):
                step.pop(key, None)
    store, run, _ = make_run(tmp_path, change=legacy)
    store.claim_run(run)
    plan = ExecutionPlan.model_validate(json.loads(store.run(run)['snapshot'])['execution_plan'])
    ExecutionStore(store).register(plan)
    assert ExecutionStore(store).claim(run, 'execute')
