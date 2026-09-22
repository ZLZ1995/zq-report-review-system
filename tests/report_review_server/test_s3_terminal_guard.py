"""S3-01 AgentCompletionService terminal guard：任何异常出口 billing 不得留在 streaming（先红后绿）。

故障注入点（任务书 S3-01）：
- provider 开始前异常
- provider 第一个 chunk 后内部异常
- usage 后 DB commit 异常
- cipher.encrypt 异常
- wallet.charge 异常
- client disconnect（由 test_agent_completion_stream 既有用例覆盖）
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from asset_based_agent.report_review_server.models import (
    BalanceHold,
    BillingRequest,
    WalletLedger,
)
from asset_based_agent.report_review_server.services.agent_completion_service import (
    AgentCompletionService,
    PreparedStream,
)

from .test_agent_completion_stream import (
    _admin_and_user,
    _db,
    _install_provider,
    _setup_billable,
    _text_script,
)


def _service(client) -> AgentCompletionService:
    return AgentCompletionService(
        metered=client.app.state.review_job_service.metered,
        session_factory=client.app.state.session_factory)


def _begin(service, client, user, model, request_id):
    db = _db(client)
    prepared = service.begin(
        db, user_id=user['user']['user_id'], model_id=model['model_id'],
        client_request_id=request_id,
        messages=[{'role': 'user', 'content': '你好'}], tools=[], sampling={})
    assert isinstance(prepared, PreparedStream)
    return db, prepared


def _final_state(client, request_id):
    with _db(client) as db:
        billing = db.scalar(select(BillingRequest).where(
            BillingRequest.client_request_id == request_id))
        hold = db.get(BalanceHold, billing.hold_id)
        charges = list(db.scalars(select(WalletLedger).where(
            WalletLedger.reference_id == billing.billing_request_id)))
        return billing.status, billing.error_code, hold.status, charges


def test_internal_error_before_provider_start_fails_and_releases_hold(client):
    """provider 未开始：failed + release hold，不产生费用。"""
    admin, user = _admin_and_user(client)
    model = _setup_billable(client, admin, user)
    _install_provider(client, [RuntimeError('provider init boom')])
    service = _service(client)
    db, prepared = _begin(service, client, user, model, 'req-s3-pre')
    try:
        events = list(service.stream(db, prepared))
    finally:
        db.close()
    assert events[-1]['kind'] == 'error'
    assert events[-1]['data']['code'] == 'internal_error'
    status, error_code, hold_status, charges = _final_state(client, 'req-s3-pre')
    assert status == 'failed', '任何出口后 billing 不得留在 streaming'
    assert error_code == 'internal_error'
    assert hold_status == 'released'
    assert charges == []


def test_internal_error_after_first_chunk_marks_uncertain(client):
    """provider 已开始、usage 不可信：uncertain，绝不按失败放行。"""
    admin, user = _admin_and_user(client)
    model = _setup_billable(client, admin, user)
    script = [
        {'kind': 'message_start', 'data': {}},
        {'kind': 'text_delta', 'data': {'text': '半截回答'}},
        RuntimeError('mid-stream boom'),
    ]
    _install_provider(client, [script])
    service = _service(client)
    db, prepared = _begin(service, client, user, model, 'req-s3-mid')
    try:
        events = list(service.stream(db, prepared))
    finally:
        db.close()
    assert events[-1]['kind'] == 'error'
    assert events[-1]['data']['code'] == 'billing_reconciliation_required'
    status, _error_code, hold_status, charges = _final_state(client, 'req-s3-mid')
    assert status == 'uncertain', '已开始的 provider 异常不得静默失败'
    assert hold_status == 'uncertain'
    assert charges == []


def test_commit_failure_after_usage_settles_failed_with_known_usage(
        client, monkeypatch):
    """usage 后 DB commit 异常：按已知 usage 结算后 failed（重试一次成功）。"""
    admin, user = _admin_and_user(client)
    model = _setup_billable(client, admin, user)
    _install_provider(client, [_text_script('commit 故障恢复')])
    service = _service(client)
    db, prepared = _begin(service, client, user, model, 'req-s3-commit')
    original_commit = Session.commit
    fired = {'count': 0}

    def flaky_commit(self):
        if self is db and not fired['count']:
            fired['count'] += 1
            raise RuntimeError('commit boom')
        return original_commit(self)

    monkeypatch.setattr(Session, 'commit', flaky_commit)
    try:
        events = list(service.stream(db, prepared))
    finally:
        db.close()
    assert events[-1]['kind'] == 'error'
    assert events[-1]['data']['code'] == 'internal_error'
    status, _error_code, hold_status, charges = _final_state(
        client, 'req-s3-commit')
    assert status == 'failed', '已拿到可信 usage：按已知 usage 结算后 failed'
    assert hold_status == 'captured'
    assert len(charges) == 1, '必须按已知用量恰好结算一次'


def test_encrypt_failure_after_usage_settles_failed_with_known_usage(
        client, monkeypatch):
    """cipher.encrypt 异常：按已知 usage 结算后 failed。"""
    admin, user = _admin_and_user(client)
    model = _setup_billable(client, admin, user)
    _install_provider(client, [_text_script('加密故障')])
    service = _service(client)
    db, prepared = _begin(service, client, user, model, 'req-s3-encrypt')

    def boom_encrypt(*args, **kwargs):
        raise RuntimeError('encrypt boom')

    monkeypatch.setattr(service.cipher, 'encrypt', boom_encrypt)
    try:
        events = list(service.stream(db, prepared))
    finally:
        db.close()
    assert events[-1]['kind'] == 'error'
    assert events[-1]['data']['code'] == 'internal_error'
    status, _error_code, hold_status, charges = _final_state(
        client, 'req-s3-encrypt')
    assert status == 'failed'
    assert hold_status == 'captured'
    assert len(charges) == 1


def test_wallet_charge_failure_retries_and_settles_failed(client, monkeypatch):
    """wallet.charge 异常一次：回滚后按已知 usage 重新结算为 failed。"""
    admin, user = _admin_and_user(client)
    model = _setup_billable(client, admin, user)
    _install_provider(client, [_text_script('扣费故障')])
    service = _service(client)
    db, prepared = _begin(service, client, user, model, 'req-s3-charge')
    metered = client.app.state.review_job_service.metered
    original_charge = metered.wallet_service.charge
    fired = {'count': 0}

    def flaky_charge(*args, **kwargs):
        if not fired['count']:
            fired['count'] += 1
            raise RuntimeError('charge boom')
        return original_charge(*args, **kwargs)

    monkeypatch.setattr(metered.wallet_service, 'charge', flaky_charge)
    try:
        events = list(service.stream(db, prepared))
    finally:
        db.close()
    assert events[-1]['kind'] == 'error'
    assert events[-1]['data']['code'] == 'internal_error'
    status, _error_code, hold_status, charges = _final_state(
        client, 'req-s3-charge')
    assert status == 'failed'
    assert hold_status == 'captured'
    assert len(charges) == 1, '重试后必须恰好扣费一次，不得双扣'


def test_unrecoverable_settlement_failure_marks_uncertain(client, monkeypatch):
    """结算反复失败（commit 持续异常）：落 uncertain，绝不留在 streaming。"""
    admin, user = _admin_and_user(client)
    model = _setup_billable(client, admin, user)
    _install_provider(client, [_text_script('持续故障')])
    service = _service(client)
    db, prepared = _begin(service, client, user, model, 'req-s3-stuck')

    original_commit = Session.commit

    def always_fail(self):
        if self is db:
            raise RuntimeError('commit permanently broken')
        return original_commit(self)

    monkeypatch.setattr(Session, 'commit', always_fail)
    try:
        events = list(service.stream(db, prepared))
    finally:
        db.close()
    monkeypatch.undo()
    assert events[-1]['kind'] == 'error'
    assert events[-1]['data']['code'] == 'billing_reconciliation_required'
    status, _error_code, hold_status, _charges = _final_state(
        client, 'req-s3-stuck')
    assert status == 'uncertain', '结算不可恢复时必须可对账，不得永久 streaming'
    assert hold_status == 'uncertain'
