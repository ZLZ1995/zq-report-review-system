import base64
import json

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from asset_based_agent.technical_platform.updates.manifest import (
    UpdatePolicy,
    verify_manifest,
)


@pytest.fixture
def release():
    private = Ed25519PrivateKey.generate()
    public = private.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    payload = {'schema_version': 1, 'key_id': 'test-key', 'sequence': 10, 'version': '0.2.7',
               'platform': 'windows', 'arch': 'x86_64', 'url': 'https://releases.test/app.zip',
               'size': 100, 'sha256': 'a' * 64, 'protocol_min': 1, 'protocol_max': 1,
               'data_schema_min': 1, 'data_schema_max': 30, 'minimum_updater': '1.0.0',
               'issued_at': 1000, 'expires_at': 2000, 'notes': 'Synthetic release'}
    policy = UpdatePolicy(current_version='0.2.6', last_sequence=9, platform='windows',
                          arch='x86_64', protocol=1, data_schema=3, updater_version='1.0.0',
                          allowed_hosts=frozenset({'releases.test'}))
    return private, {'test-key': public}, payload, policy


def sign(private, payload):
    canonical = json.dumps(payload, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode()
    return json.dumps({'payload': payload, 'signature': base64.b64encode(private.sign(
        b'ZQ-CLIENT-RELEASE-v1\x00' + canonical)).decode()}).encode()


def test_verified_manifest_is_immutable_and_independent_of_json_spacing(release):
    private, keys, payload, policy = release
    result = verify_manifest(sign(private, payload), keys=keys, policy=policy, now=1500)
    assert result.version == '0.2.7'
    assert result.sha256 == 'a' * 64
    with pytest.raises(AttributeError):
        result.version = '9.0.0'


def test_tampering_is_rejected(release):
    private, keys, payload, policy = release
    envelope = json.loads(sign(private, payload))
    envelope['payload']['url'] = 'https://releases.test/evil.zip'
    with pytest.raises(ValueError, match='signature'):
        verify_manifest(json.dumps(envelope).encode(), keys=keys, policy=policy, now=1500)


@pytest.mark.parametrize('field,value', [
    ('version', '0.2.5'), ('version', '0.2.6'), ('version', '00.2.7'),
    ('sequence', 9), ('sequence', True), ('schema_version', 2),
    ('platform', 'linux'), ('arch', 'arm64'), ('protocol_min', 2),
    ('data_schema_max', 2), ('minimum_updater', '2.0.0'),
    ('expires_at', 1400), ('issued_at', 1600), ('size', -1),
    ('sha256', 'not-a-hash'), ('url', 'http://releases.test/app.zip'),
    ('url', 'https://releases.test.evil.test/app.zip'),
    ('url', 'https://user:password@releases.test/app.zip'),
    ('url', 'https://releases.test:444/app.zip'), ('url', 'https://releases.test/app.zip#fragment'),
    ('unknown', 'field'),
])
def test_invalid_even_when_signed(release, field, value):
    private, keys, payload, policy = release
    payload[field] = value
    with pytest.raises(ValueError):
        verify_manifest(sign(private, payload), keys=keys, policy=policy, now=1500)


@pytest.mark.parametrize('revoked', [False, True])
def test_unknown_and_revoked_keys_rejected(release, revoked):
    private, keys, payload, policy = release
    with pytest.raises(ValueError, match='key'):
        verify_manifest(sign(private, payload), keys=keys if revoked else {}, policy=policy,
                        revoked_keys=frozenset({'test-key'}) if revoked else frozenset(), now=1500)


def test_duplicate_fields_and_oversized_envelopes_rejected(release):
    private, keys, payload, policy = release
    raw = sign(private, payload)
    for invalid in [raw.replace(b'"sequence": 10', b'"sequence": 1, "sequence": 10'), b' ' * 65537]:
        with pytest.raises(ValueError):
            verify_manifest(invalid, keys=keys, policy=policy, now=1500)

