import hashlib
import json
from types import SimpleNamespace

import pytest

from asset_based_agent.technical_platform.client_update import (
    available_release,
    stage_update_request,
)
from asset_based_agent.technical_platform.storage_layout import StorageLayout
from asset_based_agent.technical_platform.updates.manifest import UpdatePolicy


def release_record(version='0.2.7'):
    record = {
        'status': 'stable',
        'version': version,
        'sequence': 2,
        'manifest_sha256': '',
        'manifest': {
            'payload': {
                'schema_version': 1,
                'key_id': 'zq-release-2026-01',
                'sequence': 2,
                'version': version,
                'platform': 'windows',
                'arch': 'x86_64',
                'url': 'https://github.com/example/release.zip',
                'size': 10,
                'sha256': 'b' * 64,
                'protocol_min': 1,
                'protocol_max': 1,
                'data_schema_min': 10,
                'data_schema_max': 11,
                'minimum_updater': '1.0.0',
                'issued_at': 1,
                'expires_at': 9999999999,
                'notes': 'test',
            },
            'signature': 'signature',
        },
    }
    raw = json.dumps(record['manifest'], sort_keys=True, separators=(',', ':'),
                     ensure_ascii=True).encode('ascii')
    record['manifest_sha256'] = hashlib.sha256(raw).hexdigest()
    return record


def test_available_release_only_returns_new_stable_version():
    assert available_release({'current_release': release_record()}, '0.2.6')['version'] == '0.2.7'
    assert available_release({'current_release': release_record('0.2.6')}, '0.2.6') is None
    record = release_record()
    record['status'] = 'canary'
    assert available_release({'current_release': record}, '0.2.6') is None


def test_stage_update_writes_bounded_request_for_independent_updater(tmp_path):
    program = tmp_path / 'program'
    data = tmp_path / 'data'
    installation = tmp_path / 'installation'
    for path in (program, data, installation):
        path.mkdir()
    updater = installation / 'ZQ技术平台更新器.exe'
    updater.write_bytes(b'updater')
    policy = UpdatePolicy('0.2.6', 1, 'windows', 'x86_64', 1, 10, '1.0.0',
                          frozenset({'github.com'}))
    (installation / 'installation-policy.json').write_text(json.dumps({
        **vars(policy), 'allowed_hosts': sorted(policy.allowed_hosts),
    }), encoding='utf-8')
    database = data / 'project.sqlite'
    database.write_bytes(b'database')
    layout = StorageLayout(program, data, 'alice')
    attempt = layout.update_staging / 'update-1'
    ready = attempt / 'ready'
    ready.mkdir(parents=True)
    package = attempt / 'package.partial'
    package.write_bytes(b'package')
    captured = {}

    def prepare(raw, **kwargs):
        captured['raw'] = raw
        captured.update(kwargs)
        return SimpleNamespace(directory=ready, signed_manifest=raw)

    request = stage_update_request(
        release_record(),
        installation_root=installation,
        layout=layout,
        databases=(database,),
        now=100,
        process_id=1234,
        prepare=prepare,
    )
    assert request.executable == updater
    assert '--wait-pid' in request.command
    assert '1234' in request.command
    assert json.loads(request.manifest.read_text(encoding='ascii'))['payload']['version'] == '0.2.7'
    assert json.loads(request.inventory.read_text(encoding='utf-8')) == [str(database)]
    assert request.package == package
    assert captured['policy'] == policy


def test_stage_update_rejects_unmanaged_or_missing_database(tmp_path):
    program, data = tmp_path / 'program', tmp_path / 'data'
    program.mkdir()
    data.mkdir()
    layout = StorageLayout(program, data, 'alice')
    with pytest.raises(ValueError, match='托管'):
        stage_update_request(release_record(), installation_root=None, layout=layout,
                             databases=(), now=100, process_id=1)
