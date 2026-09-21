from decimal import Decimal

import pytest
from sqlalchemy import select

from asset_based_agent.report_review_server.models import (
    BalanceHold,
    BillingRequest,
    User,
    Wallet,
    WalletLedger,
)
from asset_based_agent.report_review_server.services.auth_service import ServiceError
from asset_based_agent.report_review_server.services.metered_model_service import (
    MeteredModelService,
)
from asset_based_agent.report_review_server.services.provider_gateway import (
    NormalizedUsage,
    ProviderCallError,
)
from tests.report_review_server.test_metered_model_service import (
    FakeProviderClient,
    _seed_billing_case,
)


def setup_unknown(client):
    user, model = _seed_billing_case(client)
    metered = MeteredModelService(client.app.state.settings, FakeProviderClient([
        ProviderCallError('provider_usage_missing', 'synthetic', retryable=False)]))
    with client.app.state.session_factory() as db:
        with pytest.raises(ServiceError):
            metered.execute(db, user_id=user, model_id=model, client_request_id='unknown',
                            estimated_usage=NormalizedUsage(input_tokens=1000), payload={})
        hold = db.scalar(select(BalanceHold))
        admin = db.scalar(select(User).where(User.role == 'admin'))
        return user, hold.hold_id, admin.user_id


def test_reconciliation_is_audited_and_idempotent(client):
    from asset_based_agent.report_review_server.models import BillingReconciliation
    from asset_based_agent.report_review_server.services.billing_reconciliation import (
        reconcile_hold,
    )
    user, hold, admin = setup_unknown(client)
    args = {'hold_id': hold, 'admin_user_id': admin, 'confirmed_amount': Decimal('0.12'),
            'evidence_sha256': 'a' * 64, 'evidence_reference': 'SUPPORT-001'}
    with client.app.state.session_factory() as db:
        first = reconcile_hold(db, **args)
        again = reconcile_hold(db, **args)
        assert first.reconciliation_id == again.reconciliation_id
        assert db.get(Wallet, user).balance == Decimal('99.88')
        assert len(list(db.scalars(select(WalletLedger)))) == 1
        assert len(list(db.scalars(select(BillingReconciliation)))) == 1
        assert db.get(BalanceHold, hold).status == 'captured'
        assert db.scalar(select(BillingRequest)).status == 'failed'
        with pytest.raises(ServiceError) as caught:
            reconcile_hold(db, **{**args, 'confirmed_amount': Decimal('0.13')})
        assert caught.value.code == 'reconciliation_conflict'


def test_non_admin_and_invalid_evidence_cannot_release_hold(client):
    from asset_based_agent.report_review_server.services.billing_reconciliation import (
        reconcile_hold,
    )
    user, hold, admin = setup_unknown(client)
    with client.app.state.session_factory() as db:
        for actor, amount, evidence in [(user, Decimal(0), 'a' * 64),
                                        (admin, Decimal('NaN'), 'a' * 64),
                                        (admin, Decimal(0), '')]:
            with pytest.raises(ServiceError):
                reconcile_hold(db, hold_id=hold, admin_user_id=actor, confirmed_amount=amount,
                               evidence_sha256=evidence, evidence_reference='SUPPORT-001')
        assert db.get(BalanceHold, hold).status == 'uncertain'
        assert db.get(Wallet, user).balance == Decimal(100)


def test_reconciliation_rolls_back_entire_transaction(client, monkeypatch):
    from asset_based_agent.report_review_server.services import (
        billing_reconciliation as module,
    )
    user, hold, admin = setup_unknown(client)
    original = module.WalletService.charge
    def failing(self, *args, **kwargs):
        original(self, *args, **kwargs)
        raise RuntimeError('synthetic write failure')
    monkeypatch.setattr(module.WalletService, 'charge', failing)
    with client.app.state.session_factory() as db:
        with pytest.raises(RuntimeError):
            module.reconcile_hold(db, hold_id=hold, admin_user_id=admin,
                                  confirmed_amount=Decimal('0.1'), evidence_sha256='a'*64,
                                  evidence_reference='SUPPORT-001')
        assert db.get(Wallet, user).balance == Decimal(100)
        assert db.get(BalanceHold, hold).status == 'uncertain'
        assert not list(db.scalars(select(WalletLedger)))


def test_zero_verified_cost_unlocks_new_reservation_without_ledger_charge(client):
    from asset_based_agent.report_review_server.services.billing_reconciliation import (
        reconcile_hold,
    )
    user, hold_id, admin = setup_unknown(client)
    with client.app.state.session_factory() as db:
        hold = db.get(BalanceHold, hold_id)
        reconcile_hold(db, hold_id=hold_id, admin_user_id=admin, confirmed_amount=Decimal(0),
                       evidence_sha256='b'*64, evidence_reference='ZERO-001')
        assert hold.status == 'released'
        assert not list(db.scalars(select(WalletLedger)))
        service = MeteredModelService(client.app.state.settings, FakeProviderClient([]))
        new = service.reserve(db, user_id=user, model_id=hold.model_id,
                              client_request_id='after', estimated_usages=[NormalizedUsage(input_tokens=1)])
        assert new.status == 'active'


def test_cannot_erase_previously_known_cost(client):
    from asset_based_agent.report_review_server.services.billing_reconciliation import (
        reconcile_hold,
    )
    user, hold_id, admin = setup_unknown(client)
    with client.app.state.session_factory() as db:
        db.get(BalanceHold, hold_id).settled_amount = Decimal('0.2')
        db.commit()
        with pytest.raises(ServiceError):
            reconcile_hold(db, hold_id=hold_id, admin_user_id=admin, confirmed_amount=Decimal('0.1'),
                           evidence_sha256='b'*64, evidence_reference='LOW-001')
        assert db.get(Wallet, user).balance == Decimal(100)
