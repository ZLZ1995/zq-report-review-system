"""Fail-closed signed release metadata. Trust roots come from the installed client.

This module never retrieves keys from the network. Key rotation requires a release
signed by a currently trusted key; revoked key IDs override the trusted key map.
The caller persists the accepted sequence only after successful installation.
"""

import base64
import binascii
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, fields
from urllib.parse import urlsplit

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

DOMAIN = b'ZQ-CLIENT-RELEASE-v1\x00'
MAX_MANIFEST_BYTES = 65536


@dataclass(frozen=True)
class UpdatePolicy:
    current_version: str
    last_sequence: int
    platform: str
    arch: str
    protocol: int
    data_schema: int
    updater_version: str
    allowed_hosts: frozenset[str]


@dataclass(frozen=True)
class ReleaseManifest:
    schema_version: int
    key_id: str
    sequence: int
    version: str
    platform: str
    arch: str
    url: str
    size: int
    sha256: str
    protocol_min: int
    protocol_max: int
    data_schema_min: int
    data_schema_max: int
    minimum_updater: str
    issued_at: int
    expires_at: int
    notes: str


def canonical_payload(payload: dict) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(',', ':'),
                      ensure_ascii=True, allow_nan=False).encode('ascii')


def version_tuple(value: str) -> tuple[int, ...]:
    if not isinstance(value, str) or not re.fullmatch(
            r'(0|[1-9][0-9]{0,5})\.(0|[1-9][0-9]{0,5})\.(0|[1-9][0-9]{0,5})', value):
        raise ValueError('invalid release version')
    return tuple(int(part) for part in value.split('.'))


def validate_download_url(value: str, allowed_hosts: frozenset[str]) -> None:
    if not isinstance(value, str) or len(value) > 2048 or any(
            ord(c) < 33 or ord(c) > 126 or c == '\\' for c in value):
        raise ValueError('invalid release URL')
    parsed = urlsplit(value)
    if (parsed.scheme != 'https' or parsed.hostname not in allowed_hosts or
            parsed.username is not None or parsed.password is not None or
            parsed.port not in (None, 443) or parsed.fragment or not parsed.path):
        raise ValueError('untrusted release URL')


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate manifest field')
        result[key] = value
    return result


def verify_manifest(raw: bytes, *, keys: Mapping[str, bytes], policy: UpdatePolicy,
                    now: int, revoked_keys: frozenset[str] = frozenset()) -> ReleaseManifest:
    if not isinstance(raw, bytes) or len(raw) > MAX_MANIFEST_BYTES:
        raise ValueError('manifest size limit exceeded')
    try:
        envelope = json.loads(raw, object_pairs_hook=_unique_object)
    except (UnicodeError, RecursionError, json.JSONDecodeError) as exc:
        raise ValueError('invalid manifest JSON') from exc
    if not isinstance(envelope, dict) or set(envelope) != {'payload', 'signature'}:
        raise ValueError('invalid manifest envelope')
    payload = envelope['payload']
    if not isinstance(payload, dict) or set(payload) != {f.name for f in fields(ReleaseManifest)}:
        raise ValueError('invalid manifest fields')
    key_id = payload['key_id']
    if (not isinstance(key_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', key_id) or
            key_id not in keys or key_id in revoked_keys):
        raise ValueError('untrusted signing key')
    try:
        signature = base64.b64decode(envelope['signature'], validate=True)
        Ed25519PublicKey.from_public_bytes(keys[key_id]).verify(
            signature, DOMAIN + canonical_payload(payload))
    except (InvalidSignature, ValueError, TypeError, binascii.Error) as exc:
        raise ValueError('invalid release signature') from exc
    for field in fields(ReleaseManifest):
        value = payload[field.name]
        if field.type is int and (type(value) is not int or not 0 <= value <= 2**53 - 1):
            raise ValueError('invalid numeric release field')
        if field.type is str and (not isinstance(value, str) or len(value) > 8192):
            raise ValueError('invalid text release field')
    release = ReleaseManifest(**payload)
    if release.schema_version != 1:
        raise ValueError('unsupported manifest schema')
    if (release.sequence <= policy.last_sequence or
            version_tuple(release.version) <= version_tuple(policy.current_version)):
        raise ValueError('release replay or downgrade refused')
    if (release.platform != policy.platform or release.arch != policy.arch or
            not release.protocol_min <= policy.protocol <= release.protocol_max or
            not release.data_schema_min <= policy.data_schema <= release.data_schema_max or
            version_tuple(release.minimum_updater) > version_tuple(policy.updater_version)):
        raise ValueError('incompatible release')
    if not release.issued_at <= now < release.expires_at:
        raise ValueError('release expired or not yet valid')
    if not 1 <= release.size <= 4 * 1024**3 or not re.fullmatch(r'[0-9a-f]{64}', release.sha256):
        raise ValueError('invalid package size or digest')
    validate_download_url(release.url, policy.allowed_hosts)
    return release

