"""S8-04 故障注入：worker 线程异常（thread exception）。

注入：executor worker 在 claim 之前（preflight 阶段）抛出内部异常 →
executor 兜底必须以安全错误码关闭 job（不复制异常文本），
job 落库 failed，hold 结算，线程池不泄漏。
"""
from __future__ import annotations

from sqlalchemy import select

from asset_based_agent.report_review_server.models import (
    BalanceHold,
    ReviewJob,
)
from asset_based_agent.report_review_server.services.review_job_executor import (
    ReviewJobExecutor,
)
from asset_based_agent.report_review_server.services.review_job_service import (
    ReviewJobService,
)
from tests.report_review_server.test_review_jobs import (
    FakeProviderClient,
    _job_payload,
    _seed_review_case,
)


class PreflightError(RuntimeError):
    code = 'preflight_broken'


def test_thread_exception_closes_job_with_safe_code(client, monkeypatch):
    user_id, model_id = _seed_review_case(client)
    service = ReviewJobService(
        client.app.state.settings, FakeProviderClient([]))
    with client.app.state.session_factory() as db:
        job = service.create_job(db, user_id=user_id,
                                 payload=_job_payload(model_id))
        job_id = job.job_id
        # 模拟 API 执行请求路径：preflight 异常发生在 claim 之前
        service.request_execution(db, user_id=user_id, job_id=job_id)

    def boom(db, *, user_id, job_id, worker_id):
        raise PreflightError('worker exploded: internal secret detail')

    monkeypatch.setattr(service, 'execute_job', boom)
    executor = ReviewJobExecutor(client.app.state.session_factory, service)
    assert executor.submit(user_id, job_id) is True
    executor.shutdown(timeout=10.0)

    with client.app.state.session_factory() as db:
        job = db.scalar(select(ReviewJob))
        hold = db.get(BalanceHold, job.hold_id)
        assert job.status == 'failed', '线程异常后 job 必须落库 failed'
        assert job.error_code == 'preflight_broken', '只保留安全公开错误码'
        assert 'internal secret detail' not in (job.error_code or '')
        assert job.worker_id is None and job.lease_expires_at is None
        assert hold.status == 'released', \
            'preflight 零用量失败必须释放冻结，不得残留 active'
