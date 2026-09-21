import json
import zipfile

import httpx
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from asset_based_agent.technical_platform.storage_layout import StorageLayout
from asset_based_agent.technical_platform.updates.coordinator import prepare_update
from asset_based_agent.technical_platform.updates.manifest import UpdatePolicy
from asset_based_agent.technical_platform.updates.signing import sign_release


def test_unsigned_manifest_never_reaches_download_or_touches_storage():
    policy = UpdatePolicy('0.2.6', 9, 'windows', 'x86_64', 1, 3, '1.0.0',
                          frozenset({'releases.test'}))
    with pytest.raises(ValueError):
        prepare_update(json.dumps({'payload': {'url': 'https://releases.test/bad'}}).encode(),
                       layout=None, policy=policy, now=1500,
                       client_factory=lambda: pytest.fail('unsigned download'))


def test_sign_verify_download_extract_keeps_old_files(tmp_path, monkeypatch):
    from asset_based_agent.technical_platform.updates import coordinator

    package = tmp_path / 'synthetic.zip'
    with zipfile.ZipFile(package, 'w') as archive:
        archive.writestr('app/synthetic.exe', b'not executable: synthetic fixture')
    key = Ed25519PrivateKey.generate()
    public = key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    monkeypatch.setattr(coordinator, 'PUBLIC_KEYS', {'test': public})
    policy = UpdatePolicy('0.2.6', 9, 'windows', 'x86_64', 1, 3, '1.0.0',
                          frozenset({'releases.test'}))
    metadata = {'schema_version': 1, 'key_id': 'test', 'sequence': 10, 'version': '0.2.7',
                'platform': 'windows', 'arch': 'x86_64', 'url': 'https://releases.test/app.zip',
                'protocol_min': 1, 'protocol_max': 1, 'data_schema_min': 1, 'data_schema_max': 30,
                'minimum_updater': '1.0.0', 'issued_at': 1000, 'expires_at': 2000, 'notes': 'test'}
    manifest = tmp_path / 'release.json'
    sign_release(metadata, package=package, private_key=key, output=manifest, policy=policy, now=1500)
    program, data = tmp_path / 'program', tmp_path / 'data'
    program.mkdir()
    data.mkdir()
    (program / 'old.exe').write_bytes(b'old version')
    (data / 'history').write_bytes(b'old history')
    layout = StorageLayout(program, data, 'synthetic-owner')
    result = prepare_update(manifest.read_bytes(), layout=layout, policy=policy, now=1500,
                            client_factory=lambda: httpx.Client(transport=httpx.MockTransport(
                                lambda _: httpx.Response(200, content=package.read_bytes()))))
    assert result.manifest.version == '0.2.7'
    assert (result.directory / 'app/synthetic.exe').is_file()
    assert (program / 'old.exe').read_bytes() == b'old version'
    assert (data / 'history').read_bytes() == b'old history'
    assert policy.last_sequence == 9  # Not installed; do not commit anti-replay state.

