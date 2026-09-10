"""Authenticated encryption for provider secrets and temporary responses."""

from __future__ import annotations

import base64
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


class SecretCipher:
    def __init__(self, key: bytes) -> None:
        if len(key) != 32:
            raise ValueError("AES-256-GCM requires a 32-byte key")
        self._cipher = AESGCM(key)

    def encrypt(self, value: str, *, purpose: str) -> str:
        nonce = os.urandom(12)
        ciphertext = self._cipher.encrypt(
            nonce,
            value.encode("utf-8"),
            purpose.encode("utf-8"),
        )
        return base64.urlsafe_b64encode(nonce + ciphertext).decode("ascii")

    def decrypt(self, value: str, *, purpose: str) -> str:
        payload = base64.urlsafe_b64decode(value.encode("ascii"))
        return self._cipher.decrypt(
            payload[:12],
            payload[12:],
            purpose.encode("utf-8"),
        ).decode("utf-8")
