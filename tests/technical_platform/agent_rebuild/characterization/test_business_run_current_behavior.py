"""S01 现状冻结：业务 Run 状态机（正确行为，重构不得破坏）。"""
import pytest
from test_consultation_routing import make_store


def test_run_state_machine_accepts_legal_path(tmp_path):
    store, _p, session = make_store(tmp_path)
    run_id = store.start_run(session, {'goal': '审核'})
    store.transition(run_id, 'running', 't')
    store.transition(run_id, 'validating', 't')
    store.transition(run_id, 'succeeded', 't')
    assert store.run(run_id)['state'] == 'succeeded'


def test_run_state_machine_rejects_illegal_transition(tmp_path):
    store, _p, session = make_store(tmp_path)
    run_id = store.start_run(session, {'goal': '审核'})
    with pytest.raises(ValueError):
        store.transition(run_id, 'succeeded', 't')
    assert store.run(run_id)['state'] == 'queued'


def test_run_cancellation_path(tmp_path):
    store, _p, session = make_store(tmp_path)
    run_id = store.start_run(session, {'goal': '审核'})
    store.transition(run_id, 'cancelled', 't')
    assert store.run(run_id)['state'] == 'cancelled'


def test_interrupted_runs_are_marked_and_not_restarted(tmp_path):
    store, _p, session = make_store(tmp_path)
    first = store.start_run(session, {'goal': '审核'})
    second = store.start_run(session, {'goal': '生成'})
    store.transition(second, 'running', 't')
    store.interrupt_active_runs()
    assert store.run(first)['state'] == 'interrupted'
    assert store.run(second)['state'] == 'interrupted'
