"""S8-04 故障注入：钱包结算失败（wallet settlement failure）。

注入：job 成功落库后 capture_hold 首次调用失败（钱包服务不可达）→
现场为「终态 job + active hold」；对账 settle_terminal_jobs 重试必须
恰好补结算一次，幂等不得重复扣费。
"""
from __future__ import annotations

import pytest
from sqlalchemy import select

from asset_based_agent.report_review_server.models import (
    BalanceHold,
    ReviewJob,
    WalletLedger,
)
from asset_based_agent.report_review_server.services.review_job_service import (
    ReviewJobService,
)
from tests.report_review_server.test_review_jobs import (
    FakeProviderClient,
    _job_payload,
    _model_response,
    _seed_review_case,
)


def _state(client):
    with client.app.state.session_factory() as db:
        job = db.scalar(select(ReviewJob))
        hold = db.get(BalanceHold, job.hold_id)
        charges = list(db.scalars(select(WalletLedger).where(
            WalletLedger.reference_id == job.job_id)))
        return job, hold, charges


def test_wallet_settlement_failure_recovered_by_reconcile(client, monkeypatch):
    user_id, model_id = _seed_review_case(client)
    service = ReviewJobService(
        client.app.state.settings,
        FakeProviderClient([_model_response(1), _model_response(2)]))
    calls = {'n': 0}
    original = service.metered.capture_hold

    def flaky_capture(*args, **kwargs):
        calls['n'] += 1
        if calls['n'] == 1:
            raise TimeoutError('wallet service unreachable')
        return original(*args, **kwargs)

    monkeypatch.setattr(service.metered, 'capture_hold', flaky_capture)
    with client.app.state.session_factory() as db:
        job = service.create_job(db, user_id=user_id,
                                 payload=_job_payload(model_id))
        with pytest.raises(TimeoutError):
            service.execute_job(db, user_id=user_id, job_id=job.job_id)

    job, hold, charges = _state(client)
    assert job.status == 'succeeded'
    assert hold.status == 'active', '结算失败现场：终态 job 残留 active hold'
    assert charges == []

    with client.app.state.session_factory() as db:
        assert service.settle_terminal_jobs(db) == 1, '对账必须补结算'
        assert service.settle_terminal_jobs(db) == 0, '对账必须幂等'
    _job, hold, charges = _state(client)
    assert hold.status == 'captured'
    assert len(charges) == 1, '必须恰好扣费一次，不得重复'
