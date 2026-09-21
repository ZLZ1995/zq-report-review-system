from __future__ import annotations

import base64

import pytest

from asset_based_agent.report_review_server.config import ServerSettings


def test_production_configuration_requires_a_long_jwt_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("REPORT_REVIEW_ENV", "production")
    monkeypatch.delenv("REPORT_REVIEW_JWT_SECRET", raising=False)

    with pytest.raises(ValueError, match="at least 32"):
        ServerSettings.from_environment()


def test_production_configuration_requires_provider_encryption_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("REPORT_REVIEW_ENV", "production")
    monkeypatch.setenv(
        "REPORT_REVIEW_JWT_SECRET",
        "production-secret-that-is-at-least-thirty-two-characters",
    )
    monkeypatch.delenv("REPORT_REVIEW_PROVIDER_ENCRYPTION_KEY", raising=False)

    with pytest.raises(ValueError, match="PROVIDER_ENCRYPTION_KEY"):
        ServerSettings.from_environment()

    monkeypatch.setenv(
        "REPORT_REVIEW_PROVIDER_ENCRYPTION_KEY",
        base64.urlsafe_b64encode(b"x" * 32).decode("ascii"),
    )
    settings = ServerSettings.from_environment()
    assert settings.encryption_key_bytes() == b"x" * 32
