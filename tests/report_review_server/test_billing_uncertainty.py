from datetime import timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

from asset_based_agent.report_review_server.models import (
    BalanceHold,
    BillingRequest,
    WalletLedger,
    utc_now,
)
from asset_based_agent.report_review_server.services.auth_service import ServiceError
from asset_based_agent.report_review_server.services.metered_model_service import (
    MeteredModelService,
)
from asset_based_agent.report_review_server.services.provider_gateway import (
    NormalizedUsage,
    ProviderCallError,
)
from asset_based_agent.report_review_server.services.review_job_service import (
    ReviewJobService,
)
from asset_based_agent.report_review_server.services.temporary_data_cleanup import (
    cleanup_expired_temporary_data,
)
from tests.report_review_server.test_metered_model_service import (
    FakeProviderClient,
    _seed_billing_case,
)
from tests.report_review_server.test_review_jobs import (
    FakeProviderClient as ReviewProvider,
)
from tests.report_review_server.test_review_jobs import _job_payload, _seed_review_case


@pytest.mark.parametrize('code', ['provider_usage_invalid', 'provider_usage_missing',
                                 'provider_network_error', 'provider_invalid_json'])
def test_unknown_cost_keeps_hold_blocks_replay_and_new_spend(client, code):
    user, model = _seed_billing_case(client)
    provider = FakeProviderClient([ProviderCallError(code, 'synthetic', retryable=True)])
    service = MeteredModelService(client.app.state.settings, provider)
    args = {'user_id': user, 'model_id': model, 'client_request_id': 'uncertain',
            'estimated_usage': NormalizedUsage(input_tokens=1000), 'payload': {'messages': []}}
    with client.app.state.session_factory() as db:
        with pytest.raises(ServiceError) as caught:
            service.execute(db, **args)
        assert caught.value.code == 'billing_reconciliation_required'
        request = db.scalar(select(BillingRequest))
        hold = db.get(BalanceHold, request.hold_id)
        assert request.status == hold.status == 'uncertain'
        assert request.completed_at is None
        assert not list(db.scalars(select(WalletLedger)))
        hold.expires_at = utc_now() - timedelta(days=1)
        db.commit()
        cleanup_expired_temporary_data(db)
        assert hold.status == 'uncertain'
        for invoke in (
            lambda: service.execute(db, **args),
            lambda: service.capture_hold(db, hold_id=hold.hold_id, reference_id='capture'),
            lambda: service.reserve(db, user_id=user, model_id=model, client_request_id='new',
                                   estimated_usages=[NormalizedUsage(input_tokens=1)]),
        ):
            with pytest.raises(ServiceError) as caught:
                invoke()
            assert caught.value.code == 'billing_reconciliation_required'
    assert provider.calls == ['deepseek']


def test_review_failure_does_not_release_unknown_cost_or_suggest_retry(client):
    user, model = _seed_review_case(client)
    provider = ReviewProvider([ProviderCallError('provider_usage_invalid', 'synthetic', retryable=False)])
    service = ReviewJobService(client.app.state.settings, provider)
    with client.app.state.session_factory() as db:
        job = service.create_job(db, user_id=user, payload=_job_payload(model))
        for _ in range(2):
            with pytest.raises(ServiceError) as caught:
                service.execute_job(db, user_id=user, job_id=job.job_id)
            assert caught.value.code == 'billing_reconciliation_required'
        assert db.get(BalanceHold, job.hold_id).status == 'uncertain'
        assert job.error_code == 'billing_reconciliation_required'
        assert len(provider.payloads) == 1


def test_uncertain_attempt_preserves_known_cost_and_other_account_can_continue(client):
    user, model = _seed_billing_case(client)
    other_user, other_model = _seed_review_case(client)
    provider = FakeProviderClient([
        ProviderCallError('upstream_timeout', 'known', retryable=True,
                          usage=NormalizedUsage(input_tokens=100_000)),
        ProviderCallError('provider_usage_missing', 'unknown', retryable=False),
    ])
    service = MeteredModelService(client.app.state.settings, provider)
    with client.app.state.session_factory() as db:
        with pytest.raises(ServiceError):
            service.execute(db, user_id=user, model_id=model, client_request_id='partial',
                estimated_usage=NormalizedUsage(input_tokens=100_000), payload={})
        request = db.scalar(select(BillingRequest))
        hold = db.get(BalanceHold, request.hold_id)
        assert hold.settled_amount == Decimal('0.10000000')
        assert hold.status == 'uncertain'
        # Reusing the reservation ID must not bypass the account guard.
        with pytest.raises(ServiceError) as caught:
            service.reserve(db, user_id=user, model_id=model, client_request_id='partial',
                            estimated_usages=[NormalizedUsage(input_tokens=1)])
        assert caught.value.code == 'billing_reconciliation_required'
        other = service.reserve(db, user_id=other_user, model_id=other_model,
                                client_request_id='other',
                                estimated_usages=[NormalizedUsage(input_tokens=1)])
        assert other.status == 'active'
