"""S6-02 客户端优雅关闭：超时兜底必须留下 durable unknown 检查点（先红后绿）。

规则（总任务书 S6-02 客户端）：关闭时所有运行任务应完成 durable
checkpoint，而不是只 gateway.stop()——worker 迟迟不收束时，开放中的
operation 必须被持久化为 unknown，等待重启后对账，绝不能假装还活着。
"""
from test_s2_lease import sqlite_repo


def test_mark_operations_unknown_persists_checkpoint(tmp_path):
    from asset_based_agent.technical_platform.agent_gateway import (
        mark_operations_unknown,
    )
    repo = sqlite_repo(tmp_path)
    operation = repo.begin_operation('s1', 'main', user_text='问', request_id='r1')
    marked = mark_operations_unknown(
        repo, [operation.id],
        code='client.shutdown_timeout', summary='客户端关闭超时')
    assert marked == 1
    persisted = repo.get_operation(operation.id)
    assert persisted.status == 'unknown'
    assert persisted.error_code == 'client.shutdown_timeout'


def test_mark_operations_unknown_is_idempotent_and_fault_tolerant(tmp_path):
    from asset_based_agent.technical_platform.agent_gateway import (
        mark_operations_unknown,
    )
    repo = sqlite_repo(tmp_path)
    operation = repo.begin_operation('s1', 'main', user_text='一', request_id='r1')
    marked = mark_operations_unknown(
        repo, [operation.id],
        code='client.shutdown_timeout', summary='客户端关闭超时')
    assert marked == 1
    # 重复标记幂等：再次调用不应报错
    marked_again = mark_operations_unknown(
        repo, [operation.id],
        code='client.shutdown_timeout', summary='客户端关闭超时')
    assert marked_again == 1
    # 不存在的 operation 不得拖垮整批
    marked_bad = mark_operations_unknown(
        repo, ['missing-id', operation.id],
        code='client.shutdown_timeout', summary='客户端关闭超时')
    assert marked_bad >= 1
    assert repo.get_operation(operation.id).status == 'unknown'
