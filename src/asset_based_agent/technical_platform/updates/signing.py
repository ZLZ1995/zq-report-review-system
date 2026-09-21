"""Offline release signing primitive. No private-key generation or persistence."""

import base64
import hashlib
import json
import os
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from .manifest import DOMAIN, UpdatePolicy, canonical_payload, verify_manifest


def sign_release(metadata: dict, *, package: Path, private_key: Ed25519PrivateKey,
                 output: Path, policy: UpdatePolicy, now: int) -> None:
    """Bind actual bytes and verify metadata before exclusive immutable publication.

    The signing environment supplies a protected key and a trusted release policy.
    Interrupted writes remain unpublished/incomplete and cannot be overwritten by
    retry: the operator must choose a new release path after examining the failure.
    """
    if output.exists():
        raise FileExistsError('release manifests are immutable')
    if not isinstance(private_key, Ed25519PrivateKey):
        raise TypeError('Ed25519 signing key required')
    hasher = hashlib.sha256()
    size = 0
    with package.open('rb') as source:
        while chunk := source.read(1024 * 1024):
            size += len(chunk)
            if size > 4 * 1024**3:
                raise ValueError('package exceeds release limit')
            hasher.update(chunk)
    payload = {**metadata, 'size': size, 'sha256': hasher.hexdigest()}
    signature = private_key.sign(DOMAIN + canonical_payload(payload))
    raw = json.dumps({'payload': payload, 'signature': base64.b64encode(signature).decode('ascii')},
                     ensure_ascii=True, sort_keys=True, separators=(',', ':')).encode('ascii')
    key_id = payload.get('key_id')
    if not isinstance(key_id, str):
        raise TypeError('signing key ID required')
    public_key = private_key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    verify_manifest(raw, keys={key_id: public_key}, policy=policy, now=now)
    with output.open('xb') as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())

