from __future__ import annotations

import os
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal

import pytest

from asset_based_agent.report_review_server.config import ServerSettings
from asset_based_agent.report_review_server.database import (
    build_engine,
    build_session_factory,
)
from asset_based_agent.report_review_server.models import (
    ModelDefinition,
    ProviderRoute,
    User,
    Wallet,
)
from asset_based_agent.report_review_server.services.metered_model_service import (
    MeteredModelService,
)
from asset_based_agent.report_review_server.services.provider_gateway import (
    NormalizedUsage,
)

POSTGRES_URL = os.environ.get("REPORT_REVIEW_POSTGRES_TEST_URL")


class _UnusedProvider:
    def call(self, route: ProviderRoute, payload: dict[str, object]) -> object:
        raise AssertionError("provider calls are outside this reservation test")


@pytest.mark.skipif(not POSTGRES_URL, reason="isolated PostgreSQL URL is required")
def test_parallel_duplicate_reservations_return_the_same_hold() -> None:
    assert POSTGRES_URL is not None
    engine = build_engine(POSTGRES_URL)
    session_factory = build_session_factory(engine)
    unique = uuid.uuid4().hex
    with session_factory() as db:
        user = User(
            username=f"wallet-concurrency-{unique}",
            display_name="Wallet Concurrency",
            password_hash="not-used",
            status="active",
            must_change_password=False,
            billing_multiplier=Decimal(1),
        )
        model = ModelDefinition(
            code=f"wallet-concurrency-model-{unique}",
            display_name="Wallet Concurrency Model",
            tier="test",
            enabled=True,
            model_multiplier=Decimal(1),
        )
        db.add_all([user, model])
        db.flush()
        db.add_all(
            [
                Wallet(user_id=user.user_id, balance=Decimal(10)),
                ProviderRoute(
                    model_id=model.model_id,
                    provider_type="openai-compatible",
                    provider_model="unused",
                    base_url="https://invalid.example",
                    api_key_ciphertext="unused",
                    priority=1,
                    enabled=True,
                    input_rate=Decimal(100000),
                    output_rate=Decimal(0),
                    cache_hit_rate=Decimal(0),
                    cache_miss_rate=Decimal(0),
                    reasoning_rate=Decimal(0),
                ),
            ]
        )
        db.commit()
        user_id = user.user_id
        model_id = model.model_id

    service = MeteredModelService(
        ServerSettings(
            database_url=POSTGRES_URL,
            jwt_secret="wallet-concurrency-test-secret-at-least-32-characters",
            environment="test",
        ),
        _UnusedProvider(),
    )
    barrier = threading.Barrier(6)

    def reserve(_: int) -> str:
        barrier.wait(timeout=10)
        with session_factory() as db:
            hold = service.reserve(
                db,
                user_id=user_id,
                model_id=model_id,
                client_request_id=f"duplicate-{unique}",
                estimated_usages=[NormalizedUsage(input_tokens=1)],
            )
            return hold.hold_id

    try:
        with ThreadPoolExecutor(max_workers=6) as executor:
            hold_ids = list(executor.map(reserve, range(6)))
        assert len(set(hold_ids)) == 1
    finally:
        engine.dispose()
