"""S5-04 统一旧 Task interrupted 状态：interrupted 不得是转换孤岛（先红后绿）。

出边要求：interrupted -> failed / running(resumed) / cancelled；
非法出边（如 interrupted -> succeeded）仍必须拒绝。
"""
from __future__ import annotations

import pytest
from test_consultation_routing import make_store


def _interrupted_run(store, session):
    run_id = store.start_run(session, {'goal': '审核'})
    store.transition(run_id, 'running', 't')
    store.interrupt_active_runs()
    assert store.run(run_id)['state'] == 'interrupted'
    return run_id


def test_interrupted_can_transition_to_failed(tmp_path):
    store, _p, session = make_store(tmp_path)
    run_id = _interrupted_run(store, session)
    store.transition(run_id, 'failed', '核对后确认失败')
    assert store.run(run_id)['state'] == 'failed'


def test_interrupted_can_transition_to_running_as_resume(tmp_path):
    store, _p, session = make_store(tmp_path)
    run_id = _interrupted_run(store, session)
    store.transition(run_id, 'running', '从检查点恢复执行')
    assert store.run(run_id)['state'] == 'running'


def test_interrupted_can_transition_to_cancelled(tmp_path):
    store, _p, session = make_store(tmp_path)
    run_id = _interrupted_run(store, session)
    store.transition(run_id, 'cancelled', '用户放弃中断任务')
    assert store.run(run_id)['state'] == 'cancelled'


def test_interrupted_cannot_jump_to_succeeded(tmp_path):
    store, _p, session = make_store(tmp_path)
    run_id = _interrupted_run(store, session)
    with pytest.raises(ValueError):
        store.transition(run_id, 'succeeded', '不得跳过执行直接成功')
    assert store.run(run_id)['state'] == 'interrupted'
