"""S8-04 故障注入套件共享 fixture。

client fixture 复制自 tests/report_review_server/conftest.py
（pytest fixture 不跨目录继承，此处独立维护）。
"""
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
