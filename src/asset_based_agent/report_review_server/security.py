"""Password and token primitives."""

from __future__ import annotations

import hashlib
import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

from .config import ServerSettings

_PASSWORD_HASHER = PasswordHasher()
_JWT_ALGORITHM = "HS256"


def hash_password(password: str, *, customer: bool = False) -> str:
    if customer:
        if not re.fullmatch(r"[A-Za-z0-9]{8,16}", password) or not re.search(r"[0-9]", password):
            raise ValueError("客户密码须为8–16位纯数字或数字与英文字母组合，区分大小写。")
    else:
        validate_password(password)
    return _PASSWORD_HASHER.hash(password)


def verify_password(password: str, encoded: str) -> bool:
    try:
        return _PASSWORD_HASHER.verify(encoded, password)
    except (VerificationError, InvalidHashError):
        return False


def validate_password(password: str) -> None:
    if len(password) < 12:
        raise ValueError("password must contain at least 12 characters")
    if len(password) > 256:
        raise ValueError("password is too long")


def new_refresh_token() -> str:
    return secrets.token_urlsafe(48)


def hash_refresh_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def issue_access_token(
    settings: ServerSettings,
    *,
    user_id: str,
    session_id: str,
    role: str,
) -> tuple[str, int]:
    now = datetime.now(timezone.utc)
    lifetime = timedelta(minutes=settings.access_token_minutes)
    payload = {
        "sub": user_id,
        "sid": session_id,
        "role": role,
        "type": "access",
        "iat": now,
        "exp": now + lifetime,
    }
    return (
        jwt.encode(payload, settings.jwt_secret, algorithm=_JWT_ALGORITHM),
        int(lifetime.total_seconds()),
    )


def decode_access_token(settings: ServerSettings, token: str) -> dict[str, Any]:
    return jwt.decode(token, settings.jwt_secret, algorithms=[_JWT_ALGORITHM])
