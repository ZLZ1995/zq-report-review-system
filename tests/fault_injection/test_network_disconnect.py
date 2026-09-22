"""S8-04 故障注入：网络中断 / HTTP 超时。

注入：provider 调用抛 httpx.ConnectError / httpx.ReadTimeout →
ReviewJob 必须进入 failed 终态，hold 必须被结算（不得残留 active），
异常干净抛出，不得有裸 AttributeError/TypeError。
"""
from __future__ import annotations

import httpx
import pytest
from sqlalchemy import select

from asset_based_agent.report_review_server.models import (
    BalanceHold,
    ReviewJob,
)
from asset_based_agent.report_review_server.services.provider_gateway import (
    ProviderCallError,
)
from asset_based_agent.report_review_server.services.review_job_service import (
    ReviewJobService,
)
from tests.report_review_server.test_review_jobs import (
    FakeProviderClient,
    _job_payload,
    _seed_review_case,
)


def _run_job_with_fault(client, fault):
    user_id, model_id = _seed_review_case(client)
    service = ReviewJobService(
        client.app.state.settings, FakeProviderClient([fault]))
    with client.app.state.session_factory() as db:
        job = service.create_job(db, user_id=user_id,
                                 payload=_job_payload(model_id))
        job_id = job.job_id
        with pytest.raises(Exception) as exc_info:
            service.execute_job(db, user_id=user_id, job_id=job_id)
    assert isinstance(exc_info.value, (httpx.HTTPError, ProviderCallError)), \
        f'异常必须干净分类，不得裸穿透: {type(exc_info.value)!r}'
    with client.app.state.session_factory() as db:
        job = db.scalar(select(ReviewJob))
        hold = db.get(BalanceHold, job.hold_id)
        assert job.status == 'failed', '网络故障后 job 必须进入 failed 终态'
        assert job.completed_at is not None
        assert job.worker_id is None and job.lease_expires_at is None
        assert hold.status != 'active', '失败后 hold 不得残留 active'


def test_network_disconnect_fails_job_and_settles_hold(client):
    _run_job_with_fault(client, httpx.ConnectError('connection refused'))


def test_http_timeout_fails_job_and_settles_hold(client):
    _run_job_with_fault(client, httpx.ReadTimeout('read timed out'))
