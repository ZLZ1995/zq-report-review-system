from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from asset_based_agent.report_review_server.api import create_app
from asset_based_agent.report_review_server.config import ServerSettings
from asset_based_agent.report_review_server.services.auth_service import (
    bootstrap_admin,
)


@pytest.fixture()
def client() -> Iterator[TestClient]:
    settings = ServerSettings(
        database_url="sqlite+pysqlite:///:memory:",
        jwt_secret="test-secret-that-is-at-least-thirty-two-characters",
        environment="test",
    )
    app = create_app(settings)
    bootstrap_admin(
        app.state.session_factory,
        username="admin",
        password="AdminPassword123!",
        display_name="Administrator",
    )
    with TestClient(app) as test_client:
        yield test_client


def login(
    client: TestClient,
    username: str,
    password: str,
    *,
    instance: str,
) -> dict[str, object]:
    response = client.post(
        "/api/v1/auth/login",
        json={
            "username": username,
            "password": password,
            "client_instance_id": instance,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}
