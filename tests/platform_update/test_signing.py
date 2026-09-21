import hashlib
import json

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from asset_based_agent.technical_platform.updates.manifest import (
    UpdatePolicy,
    verify_manifest,
)
from asset_based_agent.technical_platform.updates.signing import sign_release


def test_signing_binds_actual_package_and_never_overwrites_manifest(tmp_path):
    package = tmp_path / 'candidate.zip'
    package.write_bytes(b'synthetic package')
    key = Ed25519PrivateKey.generate()
    metadata = {'schema_version': 1, 'key_id': 'test', 'sequence': 10, 'version': '0.2.7',
                'platform': 'windows', 'arch': 'x86_64', 'url': 'https://releases.test/app.zip',
                'protocol_min': 1, 'protocol_max': 1, 'data_schema_min': 1, 'data_schema_max': 30,
                'minimum_updater': '1.0.0', 'issued_at': 1000, 'expires_at': 2000, 'notes': 'test'}
    policy = UpdatePolicy('0.2.6', 9, 'windows', 'x86_64', 1, 3, '1.0.0',
                          frozenset({'releases.test'}))
    output = tmp_path / 'release.json'
    sign_release(metadata, package=package, private_key=key, output=output, policy=policy, now=1500)
    raw = output.read_bytes()
    release = verify_manifest(raw, keys={'test': key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)},
                              policy=policy, now=1500)
    assert release.sha256 == hashlib.sha256(package.read_bytes()).hexdigest()
    assert release.size == package.stat().st_size
    assert 'private' not in json.loads(raw)
    with pytest.raises(FileExistsError):
        sign_release(metadata, package=package, private_key=key, output=output, policy=policy, now=1500)
    assert output.read_bytes() == raw
    metadata['url'] = 'http://releases.test/bad.zip'
    with pytest.raises(ValueError):
        sign_release(metadata, package=package, private_key=key, output=tmp_path / 'bad.json',
                     policy=policy, now=1500)
    assert not (tmp_path / 'bad.json').exists()

