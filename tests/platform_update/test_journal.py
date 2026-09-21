import base64
import json

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from asset_based_agent.technical_platform.updates.journal import UpdateJournal
from asset_based_agent.technical_platform.updates.manifest import (
    DOMAIN,
    UpdatePolicy,
    canonical_payload,
)


@pytest.fixture
def setup(tmp_path):
    key = Ed25519PrivateKey.generate()
    keys = {'test': key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)}
    policy = UpdatePolicy('0.2.6', 9, 'windows', 'x86_64', 1, 10, '1.0.0',
                          frozenset({'releases.test'}))
    path = tmp_path / 'update-state.sqlite'
    UpdateJournal.initialize(path, policy)
    def signed(version='0.2.7', sequence=10):
        payload = {'schema_version': 1, 'key_id': 'test', 'sequence': sequence, 'version': version,
                   'platform': 'windows', 'arch': 'x86_64', 'url': 'https://releases.test/app.zip',
                   'size': 100, 'sha256': 'a' * 64, 'protocol_min': 1, 'protocol_max': 1,
                   'data_schema_min': 1, 'data_schema_max': 30, 'minimum_updater': '1.0.0',
                   'issued_at': 1000, 'expires_at': 2000, 'notes': 'synthetic'}
        return json.dumps({'payload': payload, 'signature': base64.b64encode(
            key.sign(DOMAIN + canonical_payload(payload))).decode()}).encode()
    return path, keys, policy, signed


def test_two_sequential_updates_commit_only_after_health(setup):
    path, keys, policy, signed = setup
    journal = UpdateJournal(path, policy, keys=keys)
    for version, seq in [('0.2.7', 10), ('0.2.8', 11)]:
        old = journal.launch_version()
        token = journal.begin(signed(version, seq), now=1500)
        with pytest.raises(ValueError):
            journal.launch_version()
        with pytest.raises(ValueError):
            journal.complete(token, package_sha256='a' * 64)
        journal.backup_verified(token, backup_sha256='b' * 64)
        journal.activating(token)
        assert journal.snapshot()['active_version'] == old
        journal.complete(token, package_sha256='a' * 64)
        assert UpdateJournal(path, policy, keys=keys).launch_version() == version
    with pytest.raises(ValueError):
        journal.begin(signed('0.2.7', 10), now=1500)


def test_restart_during_activation_blocks_launch_and_blind_retry(setup):
    path, keys, policy, signed = setup
    journal = UpdateJournal(path, policy, keys=keys)
    token = journal.begin(signed(), now=1500)
    journal.backup_verified(token, backup_sha256='b' * 64)
    journal.activating(token)
    resumed = UpdateJournal(path, policy, keys=keys)
    with pytest.raises(ValueError):
        resumed.launch_version()
    with pytest.raises(ValueError):
        resumed.begin(signed(), now=1500)
    resumed.fail(token)
    assert resumed.snapshot()['phase'] == 'recovery_required'
    with pytest.raises(ValueError):
        resumed.launch_version()
    assert resumed.snapshot()['active_version'] == '0.2.6'


def test_failure_before_activation_can_retry_and_stale_token_cannot_complete(setup):
    path, keys, policy, signed = setup
    journal = UpdateJournal(path, policy, keys=keys)
    token = journal.begin(signed(), now=1500)
    journal.fail(token)
    assert journal.launch_version() == '0.2.6'
    new = journal.begin(signed(), now=1500)
    assert new != token
    with pytest.raises(ValueError):
        journal.backup_verified(token, backup_sha256='b' * 64)
    journal.backup_verified(new, backup_sha256='b' * 64)
    journal.activating(new)
    with pytest.raises(ValueError):
        journal.complete(new, package_sha256='c' * 64)
    assert journal.snapshot()['phase'] == 'activating'


def test_signature_is_checked_again_before_recording_pending(setup):
    path, keys, policy, signed = setup
    journal = UpdateJournal(path, policy, keys=keys)
    raw = json.loads(signed())
    raw['payload']['version'] = '9.0.0'
    with pytest.raises(ValueError):
        journal.begin(json.dumps(raw).encode(), now=1500)
    assert journal.launch_version() == '0.2.6'
    with pytest.raises(FileExistsError):
        UpdateJournal.initialize(path, policy)

