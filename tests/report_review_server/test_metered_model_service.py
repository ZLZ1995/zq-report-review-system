from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import select

from asset_based_agent.report_review_server.models import (
    BalanceHold,
    BillingRequest,
    ModelDefinition,
    ProviderAttempt,
    ProviderRoute,
    User,
    Wallet,
    WalletLedger,
)
from asset_based_agent.report_review_server.services.auth_service import ServiceError
from asset_based_agent.report_review_server.services.metered_model_service import (
    InsufficientBalanceError,
    MeteredExecutionError,
    MeteredModelService,
)
from asset_based_agent.report_review_server.services.provider_gateway import (
    NormalizedUsage,
    ProviderCallError,
    ProviderResponse,
    normalize_openai_usage,
)


class FakeProviderClient:
    def __init__(self, outcomes: list[object]) -> None:
        self.outcomes = list(outcomes)
        self.calls: list[str] = []

    def call(self, route: ProviderRoute, payload: dict[str, object]) -> ProviderResponse:
        self.calls.append(route.provider_type)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        assert isinstance(outcome, ProviderResponse)
        return outcome


def _seed_billing_case(client, *, balance: str = "100.00"):
    session_factory = client.app.state.session_factory
    with session_factory() as db:
        user = User(
            username="metered-user",
            display_name="Metered User",
            password_hash="not-used-in-service-test",
            role="user",
            status="active",
            must_change_password=False,
            billing_multiplier=Decimal("1.000000"),
        )
        model = ModelDefinition(
            code="deepseek-chat",
            display_name="DeepSeek Chat",
            tier="economy",
            enabled=True,
            model_multiplier=Decimal("1.000000"),
            max_output_tokens=8192,
        )
        db.add_all([user, model])
        db.flush()
        db.add(Wallet(user_id=user.user_id, balance=Decimal(balance)))
        db.add_all(
            [
                ProviderRoute(
                    model_id=model.model_id,
                    provider_type="deepseek",
                    provider_model="deepseek-chat",
                    base_url="https://api.deepseek.com",
                    api_key_ciphertext="encrypted-a",
                    priority=10,
                    enabled=True,
                    input_rate=Decimal("1.00000000"),
                    output_rate=Decimal("2.00000000"),
                    cache_hit_rate=Decimal("0.20000000"),
                    cache_miss_rate=Decimal("1.00000000"),
                    reasoning_rate=Decimal("2.00000000"),
                ),
                ProviderRoute(
                    model_id=model.model_id,
                    provider_type="openai_compatible",
                    provider_model="deepseek-chat",
                    base_url="https://relay.invalid",
                    api_key_ciphertext="encrypted-b",
                    priority=20,
                    enabled=True,
                    input_rate=Decimal("1.50000000"),
                    output_rate=Decimal("2.50000000"),
                    cache_hit_rate=Decimal("1.50000000"),
                    cache_miss_rate=Decimal("1.50000000"),
                    reasoning_rate=Decimal("2.50000000"),
                ),
            ]
        )
        db.commit()
        return user.user_id, model.model_id


def test_usage_normalization_separates_cache_and_reasoning_tokens() -> None:
    usage = normalize_openai_usage(
        {
            "prompt_tokens": 1_000,
            "completion_tokens": 500,
            "prompt_cache_hit_tokens": 300,
            "prompt_cache_miss_tokens": 600,
            "completion_tokens_details": {"reasoning_tokens": 200},
        }
    )

    assert usage == NormalizedUsage(
        input_tokens=100,
        output_tokens=300,
        cache_hit_tokens=300,
        cache_miss_tokens=600,
        reasoning_tokens=200,
    )


def test_insufficient_balance_stops_before_provider_call(client) -> None:
    user_id, model_id = _seed_billing_case(client, balance="0.01")
    provider = FakeProviderClient([])
    service = MeteredModelService(client.app.state.settings, provider)

    with client.app.state.session_factory() as db:
        with pytest.raises(InsufficientBalanceError):
            service.execute(
                db,
                user_id=user_id,
                model_id=model_id,
                client_request_id="REQ-INSUFFICIENT",
                estimated_usage=NormalizedUsage(
                    input_tokens=100_000,
                    output_tokens=100_000,
                ),
                payload={"messages": []},
            )

    assert provider.calls == []


def test_failover_charges_usage_from_failed_and_successful_attempts(client) -> None:
    user_id, model_id = _seed_billing_case(client)
    provider = FakeProviderClient(
        [
            ProviderCallError(
                "upstream_timeout",
                "DeepSeek timed out after accepting the request",
                retryable=True,
                usage=NormalizedUsage(input_tokens=100_000),
            ),
            ProviderResponse(
                payload={"result": "ok"},
                usage=NormalizedUsage(
                    input_tokens=100_000,
                    output_tokens=100_000,
                ),
            ),
        ]
    )
    service = MeteredModelService(client.app.state.settings, provider)

    with client.app.state.session_factory() as db:
        result = service.execute(
            db,
            user_id=user_id,
            model_id=model_id,
            client_request_id="REQ-FAILOVER",
            estimated_usage=NormalizedUsage(
                input_tokens=100_000,
                output_tokens=100_000,
            ),
            payload={"messages": []},
        )
        wallet = db.get(Wallet, user_id)
        attempts = list(
            db.scalars(select(ProviderAttempt).order_by(ProviderAttempt.attempt_number))
        )

    assert provider.calls == ["deepseek", "openai_compatible"]
    assert result.payload == {"result": "ok"}
    assert result.charged_amount == Decimal("0.50000000")
    assert wallet is not None
    assert wallet.balance == Decimal("99.50000000")
    assert [attempt.status for attempt in attempts] == ["failed", "succeeded"]
    assert [attempt.charged_amount for attempt in attempts] == [
        Decimal("0.10000000"),
        Decimal("0.40000000"),
    ]


def test_idempotent_request_does_not_call_or_charge_twice(client) -> None:
    user_id, model_id = _seed_billing_case(client)
    provider = FakeProviderClient(
        [
            ProviderResponse(
                payload={"issues": []},
                usage=NormalizedUsage(input_tokens=100_000),
            )
        ]
    )
    service = MeteredModelService(client.app.state.settings, provider)

    with client.app.state.session_factory() as db:
        first = service.execute(
            db,
            user_id=user_id,
            model_id=model_id,
            client_request_id="REQ-IDEMPOTENT",
            estimated_usage=NormalizedUsage(input_tokens=100_000),
            payload={"messages": []},
        )
        second = service.execute(
            db,
            user_id=user_id,
            model_id=model_id,
            client_request_id="REQ-IDEMPOTENT",
            estimated_usage=NormalizedUsage(input_tokens=100_000),
            payload={"messages": []},
        )
        ledger = list(db.scalars(select(WalletLedger)))

    assert first.payload == second.payload == {"issues": []}
    assert provider.calls == ["deepseek"]
    assert len([entry for entry in ledger if entry.entry_type == "model_charge"]) == 1


def test_all_failed_attempts_charge_only_reported_usage_and_release_hold(
    client,
) -> None:
    user_id, model_id = _seed_billing_case(client)
    provider = FakeProviderClient(
        [
            ProviderCallError(
                "deepseek_timeout",
                "timeout",
                retryable=True,
                usage=NormalizedUsage(input_tokens=100_000),
            ),
            ProviderCallError(
                "relay_timeout",
                "timeout",
                retryable=True,
                usage=NormalizedUsage(input_tokens=100_000),
            ),
        ]
    )
    service = MeteredModelService(client.app.state.settings, provider)

    with client.app.state.session_factory() as db:
        with pytest.raises(MeteredExecutionError):
            service.execute(
                db,
                user_id=user_id,
                model_id=model_id,
                client_request_id="REQ-ALL-FAILED",
                estimated_usage=NormalizedUsage(input_tokens=100_000),
                payload={"messages": []},
            )
        wallet = db.get(Wallet, user_id)
        hold = db.scalar(select(BalanceHold))
        request = db.scalar(select(BillingRequest))

    assert wallet is not None
    assert wallet.balance == Decimal("99.75000000")
    assert hold is not None
    assert hold.status == "captured"
    assert hold.settled_amount == Decimal("0.25000000")
    assert request is not None
    assert request.status == "failed"
    assert request.charged_amount == Decimal("0.25000000")


def test_idempotency_key_cannot_be_reused_for_different_payload(client) -> None:
    user_id, model_id = _seed_billing_case(client)
    provider = FakeProviderClient(
        [
            ProviderResponse(
                payload={"issues": []},
                usage=NormalizedUsage(input_tokens=100_000),
            )
        ]
    )
    service = MeteredModelService(client.app.state.settings, provider)

    with client.app.state.session_factory() as db:
        service.execute(
            db,
            user_id=user_id,
            model_id=model_id,
            client_request_id="REQ-CONFLICT",
            estimated_usage=NormalizedUsage(input_tokens=100_000),
            payload={"messages": [{"content": "first"}]},
        )
        with pytest.raises(ServiceError, match="相同请求编号"):
            service.execute(
                db,
                user_id=user_id,
                model_id=model_id,
                client_request_id="REQ-CONFLICT",
                estimated_usage=NormalizedUsage(input_tokens=100_000),
                payload={"messages": [{"content": "second"}]},
            )

    assert provider.calls == ["deepseek"]


def test_model_and_user_multipliers_are_both_applied(client) -> None:
    user_id, model_id = _seed_billing_case(client)
    with client.app.state.session_factory() as db:
        user = db.get(User, user_id)
        model = db.get(ModelDefinition, model_id)
        assert user is not None and model is not None
        user.billing_multiplier = Decimal("1.250000")
        model.model_multiplier = Decimal("1.500000")
        db.commit()
    provider = FakeProviderClient(
        [
            ProviderResponse(
                payload={"result": "ok"},
                usage=NormalizedUsage(input_tokens=100_000),
            )
        ]
    )
    service = MeteredModelService(client.app.state.settings, provider)

    with client.app.state.session_factory() as db:
        result = service.execute(
            db,
            user_id=user_id,
            model_id=model_id,
            client_request_id="REQ-MULTIPLIERS",
            estimated_usage=NormalizedUsage(input_tokens=100_000),
            payload={"messages": []},
        )

    assert result.charged_amount == Decimal("0.18750000")
