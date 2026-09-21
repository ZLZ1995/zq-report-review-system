"""S01 现状冻结：崩溃恢复。

正确行为（必须通过）：业务 run 可标记 interrupted，不自动重跑。
已知缺陷（xfail）：SES-04/TS-17 咨询轮次只存在于内存 QThread，
进程崩溃后没有 durable accepted/running 状态，无法恢复、标记或对账。
"""
import pytest
from test_consultation_routing import make_store


def test_business_run_interrupt_marks_checkpoint(tmp_path):
    store, _p, session = make_store(tmp_path)
    run_id = store.start_run(session, {'goal': '审核'})
    store.transition(run_id, 'running', 't')
    store.interrupt_active_runs()
    assert store.run(run_id)['state'] == 'interrupted'


def test_reconcile_execution_is_conservative_for_step_less_runs(tmp_path):
    """无执行步骤的 run：只报告 legacy_or_not_started，绝不自动重跑。"""
    from asset_based_agent.technical_platform.task_recovery import reconcile_execution
    store, _p, session = make_store(tmp_path)
    run_id = store.start_run(session, {'goal': '审核'})
    store.transition(run_id, 'running', 't')
    assert reconcile_execution(store, run_id) == 'legacy_or_not_started'
    assert store.run(run_id)['state'] == 'running', '核对不得改变 run 状态'


@pytest.mark.xfail(reason='SES-04：咨询轮次没有 durable 状态，崩溃后无法恢复或对账', strict=True)
def test_crashed_consult_operation_is_visible_after_reopen(tmp_path):
    store, _p, session = make_store(tmp_path)
    # 模拟：咨询在远程调用途中进程死亡（worker 未返回、未写任何记录）
    from asset_based_agent.technical_platform.sessions import sqlite_repository
    repo = sqlite_repository.SQLiteSessionRepo(store.path, 'alice')
    assert repo.open_operations(session), '重启后必须能看到未完成的咨询 operation'
