from __future__ import annotations

from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import select

from asset_based_agent.report_review_server.models import (
    ProviderRoute,
    User,
    WalletLedger,
)

from .conftest import bearer, login


def _admin_and_user(client: TestClient) -> tuple[dict[str, object], dict[str, object]]:
    admin = login(
        client,
        "admin",
        "AdminPassword123!",
        instance="admin-desktop",
    )
    created = client.post(
        "/api/v1/admin/users",
        headers=bearer(str(admin["access_token"])),
        json={
            "username": "billing-user",
            "display_name": "Billing User",
            "temporary_password": "Temporary123",
        },
    )
    assert created.status_code == 201, created.text
    user = login(
        client,
        "billing-user",
        "Temporary123",
        instance="billing-desktop",
    )
    return admin, user


def _create_model(client: TestClient, admin_token: str) -> dict[str, object]:
    response = client.post(
        "/api/v1/admin/models",
        headers=bearer(admin_token),
        json={
            "code": "deepseek-chat",
            "display_name": "DeepSeek Chat",
            "tier": "economy",
            "model_multiplier": "1.500000",
            "max_output_tokens": 8192,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_user_can_only_read_current_balance(client: TestClient) -> None:
    admin, user = _admin_and_user(client)
    user_id = str(user["user"]["user_id"])

    adjusted = client.post(
        f"/api/v1/admin/users/{user_id}/balance-adjustments",
        headers=bearer(str(admin["access_token"])),
        json={"amount": "100.12500000"},
    )
    balance = client.get(
        "/api/v1/account/balance",
        headers=bearer(str(user["access_token"])),
    )

    assert adjusted.status_code == 200
    assert adjusted.json()["balance"] == "100.13"
    assert balance.json() == {"balance": "100.13", "currency": "CNY"}
    assert "token" not in balance.text.lower()
    assert "cost" not in balance.text.lower()


def test_admin_adjustment_allows_negative_balance(client: TestClient) -> None:
    admin, user = _admin_and_user(client)
    user_id = str(user["user"]["user_id"])
    headers = bearer(str(admin["access_token"]))

    client.post(
        f"/api/v1/admin/users/{user_id}/balance-adjustments",
        headers=headers,
        json={"amount": "10.00"},
    )
    result = client.post(
        f"/api/v1/admin/users/{user_id}/balance-adjustments",
        headers=headers,
        json={"amount": "-25.50"},
    )

    assert result.status_code == 200
    assert result.json()["balance"] == "-15.50"
    with client.app.state.session_factory() as db:
        entries = list(db.scalars(select(WalletLedger).where(WalletLedger.user_id == user_id)))
    assert sum((entry.amount for entry in entries), Decimal("0")) == Decimal("-15.50000000")


def test_public_model_list_does_not_disclose_prices_or_multipliers(
    client: TestClient,
) -> None:
    admin, user = _admin_and_user(client)
    model = _create_model(client, str(admin["access_token"]))

    response = client.get(
        "/api/v1/models",
        headers=bearer(str(user["access_token"])),
    )

    assert response.status_code == 200
    assert response.json() == [
        {
            "model_id": model["model_id"],
            "code": "deepseek-chat",
            "display_name": "DeepSeek Chat",
            "tier": "economy",
        }
    ]
    assert "price" not in response.text.lower()
    assert "multiplier" not in response.text.lower()


def test_provider_api_key_is_encrypted_and_never_returned(
    client: TestClient,
) -> None:
    admin, _user = _admin_and_user(client)
    admin_token = str(admin["access_token"])
    model = _create_model(client, admin_token)

    response = client.post(
        f"/api/v1/admin/models/{model['model_id']}/routes",
        headers=bearer(admin_token),
        json={
            "provider_type": "deepseek",
            "provider_model": "deepseek-chat",
            "base_url": "https://api.deepseek.com",
            "api_key": "test-provider-secret-never-store-plain",
            "priority": 10,
            "rates": {
                "input": "1.00",
                "output": "2.00",
                "cache_hit": "0.20",
                "cache_miss": "1.00",
                "reasoning": "2.00",
            },
        },
    )

    assert response.status_code == 201, response.text
    assert response.json()["api_key_configured"] is True
    assert "test-provider-secret" not in response.text
    with client.app.state.session_factory() as db:
        route = db.scalar(select(ProviderRoute))
        assert route is not None
        assert "test-provider-secret" not in route.api_key_ciphertext


def test_admin_can_set_user_billing_multiplier(client: TestClient) -> None:
    admin, user = _admin_and_user(client)
    user_id = str(user["user"]["user_id"])

    response = client.patch(
        f"/api/v1/admin/users/{user_id}/billing-multiplier",
        headers=bearer(str(admin["access_token"])),
        json={"multiplier": "1.250000"},
    )

    assert response.status_code == 204
    with client.app.state.session_factory() as db:
        stored = db.get(User, user_id)
        assert stored is not None
        assert stored.billing_multiplier == Decimal("1.250000")
