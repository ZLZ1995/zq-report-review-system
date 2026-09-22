"""S3-03 ReviewJob 与 Hold 一致性：终态 job + active hold 中间态重启后自动 settlement（先红后绿）。

故障注入：job 终态 commit 之后、capture_hold 之前崩溃（success / failed /
cancelled 三条路径）。重启对账必须幂等，不得重复 charge。
"""
from __future__ import annotations

import pytest
from sqlalchemy import select

from asset_based_agent.report_review_server.models import (
    BalanceHold,
    ReviewJob,
    WalletLedger,
)
from asset_based_agent.report_review_server.services.provider_gateway import (
    NormalizedUsage,
    ProviderCallError,
)
from asset_based_agent.report_review_server.services.review_job_service import (
    ReviewJobService,
)

from .test_review_jobs import (
    FakeProviderClient,
    _job_payload,
    _model_response,
    _seed_review_case,
)


def _crash_capture(service, monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError('process crashed before capture_hold')
    monkeypatch.setattr(service.metered, 'capture_hold', boom)


def _state(client):
    with client.app.state.session_factory() as db:
        job = db.scalar(select(ReviewJob))
        hold = db.get(BalanceHold, job.hold_id)
        charges = list(db.scalars(select(WalletLedger).where(
            WalletLedger.reference_id == job.job_id)))
        return job, hold, charges


def test_succeeded_job_with_active_hold_is_settled_on_recovery(
        client, monkeypatch):
    """job success commit 后、capture_hold 前崩溃 → 重启自动结算一次。"""
    user_id, model_id = _seed_review_case(client)
    service = ReviewJobService(
        client.app.state.settings,
        FakeProviderClient([_model_response(1), _model_response(2)]))
    with client.app.state.session_factory() as db:
        job = service.create_job(db, user_id=user_id,
                                 payload=_job_payload(model_id))
        _crash_capture(service, monkeypatch)
        with pytest.raises(RuntimeError):
            service.execute_job(db, user_id=user_id, job_id=job.job_id)
    monkeypatch.undo()
    job, hold, charges = _state(client)
    assert job.status == 'succeeded'
    assert hold.status == 'active', '崩溃现场：终态 job 残留 active hold'
    assert charges == []
    with client.app.state.session_factory() as db:
        assert service.settle_terminal_jobs(db) == 1
    _job, hold, charges = _state(client)
    assert hold.status == 'captured'
    assert len(charges) == 1, '重启后必须恰好补结算一次'
    with client.app.state.session_factory() as db:
        assert service.settle_terminal_jobs(db) == 0, '对账必须幂等'
    _job, _hold, charges = _state(client)
    assert len(charges) == 1, '不得重复 charge'


def test_failed_job_with_active_hold_is_settled_on_recovery(
        client, monkeypatch):
    """job failed commit 后崩溃 → 重启按累计用量补结算，不重复扣费。"""
    user_id, model_id = _seed_review_case(client)
    service = ReviewJobService(
        client.app.state.settings,
        FakeProviderClient([ProviderCallError(
            'provider_http_500', '渠道故障', retryable=False,
            usage=NormalizedUsage(input_tokens=100, output_tokens=50))]))
    with client.app.state.session_factory() as db:
        job = service.create_job(db, user_id=user_id,
                                 payload=_job_payload(model_id))
        _crash_capture(service, monkeypatch)
        with pytest.raises(RuntimeError):
            service.execute_job(db, user_id=user_id, job_id=job.job_id)
    monkeypatch.undo()
    job, hold, _charges = _state(client)
    assert job.status == 'failed'
    assert hold.status == 'active'
    with client.app.state.session_factory() as db:
        assert service.settle_terminal_jobs(db) == 1
        assert service.settle_terminal_jobs(db) == 0
    _job, hold, charges = _state(client)
    assert hold.status == 'captured'
    assert len(charges) == 1


def test_cancelled_job_with_active_hold_is_released_on_recovery(
        client, monkeypatch):
    """cancelled commit 后崩溃 → 重启释放冻结（零用量不扣费）。"""
    user_id, model_id = _seed_review_case(client)
    service = ReviewJobService(
        client.app.state.settings, FakeProviderClient([]))
    with client.app.state.session_factory() as db:
        job = service.create_job(db, user_id=user_id,
                                 payload=_job_payload(model_id))
        _crash_capture(service, monkeypatch)
        with pytest.raises(RuntimeError):
            service.cancel_job(db, user_id=user_id, job_id=job.job_id)
    monkeypatch.undo()
    job, hold, _charges = _state(client)
    assert job.status == 'cancelled'
    assert hold.status == 'active'
    with client.app.state.session_factory() as db:
        assert service.settle_terminal_jobs(db) == 1
        assert service.settle_terminal_jobs(db) == 0
    _job, hold, charges = _state(client)
    assert hold.status == 'released', '零用量的取消必须释放冻结'
    assert charges == []


def test_startup_recovery_requeue_also_settles_terminal_jobs(
        client, monkeypatch):
    """启动恢复入口 recover_interrupted 必须先做终态 settlement 对账。"""
    user_id, model_id = _seed_review_case(client)
    service = ReviewJobService(
        client.app.state.settings,
        FakeProviderClient([_model_response(1), _model_response(2)]))
    with client.app.state.session_factory() as db:
        job = service.create_job(db, user_id=user_id,
                                 payload=_job_payload(model_id))
        _crash_capture(service, monkeypatch)
        with pytest.raises(RuntimeError):
            service.execute_job(db, user_id=user_id, job_id=job.job_id)
    monkeypatch.undo()
    with client.app.state.session_factory() as db:
        service.recover_interrupted(db)
    _job, hold, charges = _state(client)
    assert hold.status == 'captured', '启动恢复必须顺带完成终态 settlement'
    assert len(charges) == 1
