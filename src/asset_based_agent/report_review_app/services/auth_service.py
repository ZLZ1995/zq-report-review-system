"""Local password authentication backed by a JSON configuration file."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
from pathlib import Path
from typing import Any

PBKDF2_ALGORITHM = "pbkdf2_sha256"
PBKDF2_ITERATIONS = 600_000


class AuthenticationError(ValueError):
    """Raised when credentials are invalid without revealing which field failed."""


class AuthConfigurationError(ValueError):
    """Raised when the local user configuration is missing or malformed."""


class AuthService:
    def __init__(self, config_path: Path) -> None:
        self.config_path = config_path

    def authenticate(self, username: str, password: str) -> dict[str, str]:
        payload = self._load()
        normalized = username.strip()
        for user in payload["users"]:
            if user.get("username") != normalized or not user.get("enabled", True):
                continue
            if verify_password(password, user.get("password") or {}):
                return {
                    "username": normalized,
                    "display_name": str(user.get("display_name") or normalized),
                }
            break
        raise AuthenticationError("invalid username or password")

    def _load(self) -> dict[str, Any]:
        if not self.config_path.is_file():
            raise AuthConfigurationError("user configuration file not found")
        try:
            payload = json.loads(self.config_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise AuthConfigurationError("user configuration file is invalid") from exc
        users = payload.get("users")
        if not isinstance(users, list) or not users:
            raise AuthConfigurationError("user configuration contains no users")
        return payload


def build_password_record(
    password: str,
    *,
    iterations: int = PBKDF2_ITERATIONS,
    salt: bytes | None = None,
) -> dict[str, str | int]:
    if not password:
        raise ValueError("password is required")
    if iterations < 100_000:
        raise ValueError("PBKDF2 iterations are too low")
    actual_salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        actual_salt,
        iterations,
    )
    return {
        "algorithm": PBKDF2_ALGORITHM,
        "iterations": iterations,
        "salt": base64.b64encode(actual_salt).decode("ascii"),
        "hash": base64.b64encode(digest).decode("ascii"),
    }


def verify_password(password: str, record: dict[str, Any]) -> bool:
    if record.get("algorithm") != PBKDF2_ALGORITHM:
        return False
    try:
        iterations = int(record["iterations"])
        salt = base64.b64decode(str(record["salt"]).encode("ascii"), validate=True)
        expected = base64.b64decode(str(record["hash"]).encode("ascii"), validate=True)
    except (KeyError, TypeError, ValueError):
        return False
    actual = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        iterations,
    )
    return hmac.compare_digest(actual, expected)


def write_user_config(
    path: Path,
    *,
    username: str,
    password: str,
    display_name: str = "",
) -> Path:
    normalized = username.strip()
    if not normalized:
        raise ValueError("username is required")
    payload = {
        "schema_version": "1.0",
        "users": [
            {
                "username": normalized,
                "display_name": display_name.strip() or normalized,
                "enabled": True,
                "password": build_password_record(password),
            }
        ],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    os.replace(temporary, path)
    return path
