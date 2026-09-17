"""Environment-backed server configuration."""

from __future__ import annotations

import base64
import hashlib
import os
import re
from dataclasses import dataclass


@dataclass(frozen=True)
class ServerSettings:
    database_url: str
    jwt_secret: str
    environment: str = "development"
    access_token_minutes: int = 15
    refresh_token_days: int = 7
    provider_encryption_key: str = ""
    build_sha: str | None = None

    def __post_init__(self) -> None:
        if self.build_sha is not None and not re.fullmatch(r'[0-9a-f]{40}|[0-9a-f]{64}', self.build_sha):
            raise ValueError('REPORT_REVIEW_BUILD_SHA must be a lowercase Git commit SHA')
        if len(self.jwt_secret) < 32:
            raise ValueError("REPORT_REVIEW_JWT_SECRET must contain at least 32 characters")
        if self.access_token_minutes < 1:
            raise ValueError("access token lifetime must be positive")
        if self.refresh_token_days < 1:
            raise ValueError("refresh token lifetime must be positive")
        if self.environment == "production" and not self.provider_encryption_key:
            raise ValueError("REPORT_REVIEW_PROVIDER_ENCRYPTION_KEY is required")
        if self.provider_encryption_key:
            try:
                key = base64.urlsafe_b64decode(self.provider_encryption_key)
            except ValueError as exc:
                raise ValueError("provider encryption key is invalid") from exc
            if len(key) != 32:
                raise ValueError("provider encryption key must decode to 32 bytes")

    @classmethod
    def from_environment(cls) -> ServerSettings:
        environment = os.environ.get("REPORT_REVIEW_ENV", "development")
        secret = os.environ.get("REPORT_REVIEW_JWT_SECRET", "")
        if not secret and environment == "development":
            secret = "development-only-secret-change-before-deployment"
        return cls(
            database_url=os.environ.get(
                "REPORT_REVIEW_DATABASE_URL",
                "sqlite+pysqlite:///./report_review_server.db",
            ),
            jwt_secret=secret,
            environment=environment,
            access_token_minutes=int(os.environ.get("REPORT_REVIEW_ACCESS_TOKEN_MINUTES", "15")),
            refresh_token_days=int(os.environ.get("REPORT_REVIEW_REFRESH_TOKEN_DAYS", "7")),
            provider_encryption_key=os.environ.get("REPORT_REVIEW_PROVIDER_ENCRYPTION_KEY", ""),
            build_sha=os.environ.get('REPORT_REVIEW_BUILD_SHA') or None,
        )

    def encryption_key_bytes(self) -> bytes:
        if self.provider_encryption_key:
            return base64.urlsafe_b64decode(self.provider_encryption_key)
        return hashlib.sha256(self.jwt_secret.encode("utf-8")).digest()
