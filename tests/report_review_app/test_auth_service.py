from __future__ import annotations

import json
from pathlib import Path

import pytest

from asset_based_agent.report_review_app.services.auth_service import (
    AuthConfigurationError,
    AuthenticationError,
    AuthService,
    build_password_record,
    verify_password,
    write_user_config,
)


def test_password_record_never_contains_plaintext() -> None:
    record = build_password_record(
        "secret-passphrase",
        iterations=100_000,
        salt=b"0123456789abcdef",
    )

    assert "secret-passphrase" not in json.dumps(record)
    assert verify_password("secret-passphrase", record) is True
    assert verify_password("wrong", record) is False


def test_write_config_and_authenticate_local_user(tmp_path: Path) -> None:
    path = tmp_path / "users.json"
    write_user_config(
        path,
        username="reviewer",
        password="safe-password",
        display_name="Reviewer",
    )

    session = AuthService(path).authenticate("reviewer", "safe-password")

    assert session == {"username": "reviewer", "display_name": "Reviewer"}
    assert "safe-password" not in path.read_text(encoding="utf-8")


def test_invalid_credentials_use_generic_error(tmp_path: Path) -> None:
    path = tmp_path / "users.json"
    write_user_config(path, username="reviewer", password="safe-password")

    with pytest.raises(AuthenticationError, match="invalid username or password"):
        AuthService(path).authenticate("reviewer", "wrong")


def test_missing_user_config_is_reported(tmp_path: Path) -> None:
    with pytest.raises(AuthConfigurationError, match="not found"):
        AuthService(tmp_path / "missing.json").authenticate("user", "password")
