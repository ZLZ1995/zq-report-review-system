import pytest
from test_event_store import prepared


def test_recovery_repairs_terminal_gap_without_replaying_tool(tmp_path):
    from asset_based_agent.technical_platform.task_recovery import reconcile_execution
    store, run, _, events = prepared(tmp_path)
    events.claim(run, 'execute')
    store.transition(run, 'validating', 'synthetic')
    store.transition(run, 'succeeded', 'synthetic')
    # Simulates a crash after persisting run success, before step checkpoint.
    assert reconcile_execution(store, run) == 'succeeded'
    assert reconcile_execution(store, run) == 'succeeded'
    assert [e['kind'] for e in events.events(run)] == ['running', 'succeeded']


def test_running_is_unconfirmed_not_assumed_dead_or_restarted(tmp_path):
    from asset_based_agent.technical_platform.task_recovery import reconcile_execution
    store, run, _, events = prepared(tmp_path)
    events.claim(run, 'execute')
    assert reconcile_execution(store, run) == 'reconciliation_required'
    assert store.run(run)['state'] == 'running'
    with pytest.raises(ValueError):
        events.claim(run, 'execute')
    assert len(events.events(run)) == 1


def test_other_owner_cannot_reconcile(tmp_path):
    from asset_based_agent.technical_platform.store import PlatformStore
    from asset_based_agent.technical_platform.task_recovery import reconcile_execution
    store, run, _, _ = prepared(tmp_path)
    with pytest.raises(PermissionError):
        reconcile_execution(PlatformStore(store.path, 'bob'), run)
