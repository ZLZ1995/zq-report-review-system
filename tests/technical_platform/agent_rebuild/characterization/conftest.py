"""S01 characterization 测试共享工具。

把 tests/technical_platform 加入 sys.path，复用 K 轮已建立的测试夹具；
本目录只冻结现状，不修改生产代码。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


def failing_consult_worker(store, session, prompt):
    """同步执行一个远程理解必失败的 ConsultWorker，返回 (calls, worker)。"""
    from test_consultation_routing import SpyClient

    from asset_based_agent.report_review_app.services.remote_auth_service import (
        NetworkUnavailable,
    )
    from asset_based_agent.technical_platform.routing import ConsultWorker

    spy = SpyClient()

    def boom(payload, *, cancel=None):
        spy.understand_calls.append(payload)
        raise NetworkUnavailable('无法连接审核服务，请检查网络。')

    spy.understand_task = boom
    worker = ConsultWorker(spy, store, session, prompt, model_id='m', selected_ids=[])
    worker.run()
    return spy, worker
