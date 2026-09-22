"""S8-05 状态机 Property Tests（服务端两套）：ReviewJob / BillingRequest。

不变量（任务书 S8-05）：
1. 任何入口执行完成后，不得出现无 owner 的 running
   （running 必有 worker_id + lease；终态必清空 owner）；
2. 不得存在不可达状态（观测状态 ∈ 允许集合）；
3. terminal 不能回到 running（终态守卫拒绝再次执行/取消/重新请求）。
"""
from __future__ import annotations

import pytest
from sqlalchemy import select

from asset_based_agent.report_review_server.models import (
    BalanceHold,
    BillingRequest,
    ReviewJob,
    WalletLedger,
)
from asset_based_agent.report_review_server.services.auth_service import (
    ServiceError,
)
from asset_based_agent.report_review_server.services.metered_model_service import (
    MeteredExecutionError,
    MeteredModelService,
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

REVIEW_JOB_STATUSES = frozenset(
    {'queued', 'running', 'succeeded', 'failed', 'cancelled'})
REVIEW_JOB_TERMINAL = frozenset({'succeeded', 'failed', 'cancelled'})
BILLING_REQUEST_STATUSES = frozenset(
    {'pending', 'succeeded', 'failed', 'uncertain'})
HOLD_STATUSES = frozenset({'active', 'captured', 'released', 'uncertain'})


def _assert_job_invariants(job):
    assert job.status in REVIEW_JOB_STATUSES, f'不可达状态: {job.status}'
    if job.status == 'running':
        # 不变量 1：running 必须有 owner
        assert job.worker_id and job.lease_expires_at is not None
    if job.status in REVIEW_JOB_TERMINAL:
        assert job.completed_at is not None
        assert job.worker_id is None and job.lease_expires_at is None, \
            '终态必须清空执行 owner'


def _get_job(client, job_id):
    with client.app.state.session_factory() as db:
        return db.scalar(select(ReviewJob).where(ReviewJob.job_id == job_id))


# ------------------------------------------------------------ ReviewJob

def test_review_job_happy_path_states_and_terminal_guard(client):
    user_id, model_id = _seed_review_case(client)
    provider = FakeProviderClient([_model_response(1), _model_response(2)])
    service = ReviewJobService(client.app.state.settings, provider)
    with client.app.state.session_factory() as db:
        job = service.create_job(db, user_id=user_id,
                                 payload=_job_payload(model_id))
        job_id = job.job_id
        _assert_job_invariants(_get_job(client, job_id))

        # queued → queued(execution_requested)：幂等，不推进终态
        service.request_execution(db, user_id=user_id, job_id=job_id)
        service.request_execution(db, user_id=user_id, job_id=job_id)
        requested = _get_job(client, job_id)
        assert requested.status == 'queued'
        assert requested.execution_requested_at is not None

        service.execute_job(db, user_id=user_id, job_id=job_id)
    done = _get_job(client, job_id)
    assert done.status == 'succeeded'
    _assert_job_invariants(done)
    provider_calls = len(provider.payloads)

    with client.app.state.session_factory() as db:
        # 不变量 3：succeeded 不得回到 running/queued
        again = service.execute_job(db, user_id=user_id, job_id=job_id)
        assert again.status == 'succeeded'
        assert len(provider.payloads) == provider_calls, \
            '终态 job 不得重新调用 provider'
        reused = service.request_execution(db, user_id=user_id, job_id=job_id)
        assert reused.status == 'succeeded'
        cancelled = service.cancel_job(db, user_id=user_id, job_id=job_id)
        assert cancelled.status == 'succeeded', '终态 job 不得被 cancel 改动'
    _assert_job_invariants(_get_job(client, job_id))
    assert _get_job(client, job_id).status == 'succeeded'


def test_review_job_failure_path_terminal_and_settled(client):
    user_id, model_id = _seed_review_case(client)
    service = ReviewJobService(
        client.app.state.settings,
        FakeProviderClient([ProviderCallError(
            'provider_http_500', '渠道故障', retryable=False,
            usage=NormalizedUsage(input_tokens=100, output_tokens=50))]))
    with client.app.state.session_factory() as db:
        job = service.create_job(db, user_id=user_id,
                                 payload=_job_payload(model_id))
        job_id = job.job_id
        with pytest.raises(MeteredExecutionError):
            service.execute_job(db, user_id=user_id, job_id=job_id)
    failed = _get_job(client, job_id)
    assert failed.status == 'failed'
    _assert_job_invariants(failed)
    with client.app.state.session_factory() as db:
        hold = db.get(BalanceHold, failed.hold_id)
        assert hold.status in HOLD_STATUSES - {'active'}, \
            '终态 job 不得残留 active hold'
        # 不变量 3：failed 不得重新执行
        with pytest.raises(ServiceError):
            service.execute_job(db, user_id=user_id, job_id=job_id)


def test_review_job_cancelled_is_terminal(client):
    user_id, model_id = _seed_review_case(client)
    service = ReviewJobService(
        client.app.state.settings, FakeProviderClient([]))
    with client.app.state.session_factory() as db:
        job = service.create_job(db, user_id=user_id,
                                 payload=_job_payload(model_id))
        job_id = job.job_id
        service.cancel_job(db, user_id=user_id, job_id=job_id)
    cancelled = _get_job(client, job_id)
    assert cancelled.status == 'cancelled'
    _assert_job_invariants(cancelled)
    with client.app.state.session_factory() as db, pytest.raises(ServiceError):
        service.execute_job(db, user_id=user_id, job_id=job_id)


# --------------------------------------------------------- BillingRequest

def _metered(client, responses):
    return MeteredModelService(client.app.state.settings,
                               FakeProviderClient(responses))


def _billing_state(client, client_request_id):
    with client.app.state.session_factory() as db:
        request = db.scalar(select(BillingRequest).where(
            BillingRequest.client_request_id == client_request_id))
        hold = db.get(BalanceHold, request.hold_id)
        charges = list(db.scalars(select(WalletLedger).where(
            WalletLedger.reference_id == request.billing_request_id)))
        return request, hold, charges


def test_billing_request_success_then_replay_is_idempotent(client):
    user_id, model_id = _seed_review_case(client)
    metered = _metered(client, [{'ok': True}])
    with client.app.state.session_factory() as db:
        first = metered.execute(
            db, user_id=user_id, model_id=model_id,
            client_request_id='prop-billing-1',
            estimated_usage=NormalizedUsage(input_tokens=10, output_tokens=10),
            payload={'messages': []})
    assert first.payload == {'ok': True}

    request, hold, charges = _billing_state(client, 'prop-billing-1')
    assert request.status in BILLING_REQUEST_STATUSES
    assert request.status == 'succeeded'
    assert hold.status == 'captured'
    assert len(charges) == 1

    # 幂等重放：同 client_request_id + 同 payload → 不产生新计费
    replayed = _metered(client, [])
    with client.app.state.session_factory() as db:
        second = replayed.execute(
            db, user_id=user_id, model_id=model_id,
            client_request_id='prop-billing-1',
            estimated_usage=NormalizedUsage(input_tokens=10, output_tokens=10),
            payload={'messages': []})
    assert second.billing_request_id == first.billing_request_id
    request, hold, charges = _billing_state(client, 'prop-billing-1')
    assert request.status == 'succeeded'
    assert len(charges) == 1, '重放不得重复扣费'


def test_billing_request_failure_is_terminal_and_settled(client):
    user_id, model_id = _seed_review_case(client)
    metered = _metered(client, [ProviderCallError(
        'provider_http_500', '渠道故障', retryable=False,
        usage=NormalizedUsage(input_tokens=100, output_tokens=50))])
    with client.app.state.session_factory() as db,             pytest.raises(MeteredExecutionError):
        metered.execute(
            db, user_id=user_id, model_id=model_id,
            client_request_id='prop-billing-2',
            estimated_usage=NormalizedUsage(input_tokens=10,
                                            output_tokens=10),
            payload={'messages': []})
    request, hold, _charges = _billing_state(client, 'prop-billing-2')
    assert request.status in BILLING_REQUEST_STATUSES
    assert request.status == 'failed'
    assert request.completed_at is not None
    assert hold.status in HOLD_STATUSES - {'active'}, \
        '失败终态不得残留 active hold'
