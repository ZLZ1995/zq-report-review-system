"""S8-04 故障注入：更新中途崩溃（update mid-crash）。

注入：候选包解包阶段断电（extract_verified_package 抛错）→
journal 必须记录失败而非半成品激活，业务库不得变动，
当前版本保持不变，且重试安装必须成功。
"""
from __future__ import annotations

import base64
import hashlib
import json
import sqlite3
import zipfile
from contextlib import closing

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
)
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    PublicFormat,
)

import asset_based_agent.technical_platform.updates.installer as installer_module
from asset_based_agent.technical_platform.updates.installer import (
    install_candidate,
)
from asset_based_agent.technical_platform.updates.journal import UpdateJournal
from asset_based_agent.technical_platform.updates.manifest import (
    DOMAIN,
    UpdatePolicy,
    canonical_payload,
)
from asset_based_agent.technical_platform.updates.process_lock import (
    InstallationLock,
)


@pytest.fixture()
def fixture(tmp_path):
    root = tmp_path / 'installation'
    root.mkdir()
    (root / 'versions').mkdir()
    old = root / 'versions/0.2.6'
    old.mkdir()
    (old / 'old.exe').write_bytes(b'old')
    key = Ed25519PrivateKey.generate()
    keys = {'test': key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)}
    policy = UpdatePolicy('0.2.6', 9, 'windows', 'x86_64', 1, 10, '1.0.0',
                          frozenset({'releases.test'}))
    UpdateJournal.initialize(root / 'update-state.sqlite', policy)
    InstallationLock.initialize(root / 'installation-lock.sqlite')
    database = tmp_path / 'project.sqlite'
    with closing(sqlite3.connect(database)) as db, db:
        db.execute('CREATE TABLE messages(body TEXT)')
        db.execute("INSERT INTO messages VALUES('retain history')")
    package = tmp_path / 'package.zip'
    with zipfile.ZipFile(package, 'w') as archive:
        archive.writestr('ZQ技术平台/ZQ技术平台.exe', b'synthetic executable')

    def signed(version='0.2.7', seq=10):
        payload = {'schema_version': 1, 'key_id': 'test', 'sequence': seq,
                   'version': version, 'platform': 'windows', 'arch': 'x86_64',
                   'url': 'https://releases.test/app.zip',
                   'size': package.stat().st_size,
                   'sha256': hashlib.sha256(package.read_bytes()).hexdigest(),
                   'protocol_min': 1, 'protocol_max': 1,
                   'data_schema_min': 1, 'data_schema_max': 30,
                   'minimum_updater': '1.0.0', 'issued_at': 1000,
                   'expires_at': 2000, 'notes': 'test'}
        return json.dumps({'payload': payload, 'signature': base64.b64encode(
            key.sign(DOMAIN + canonical_payload(payload))).decode()}).encode()

    return root, policy, keys, database, package, signed


def _healthy(_executable, _work, release):
    return {'client_version': release.version, 'protocol_version': 1,
            'local_schema_version': 10}


def test_update_mid_crash_leaves_recoverable_state(fixture, monkeypatch):
    root, policy, keys, database, package, signed = fixture
    journal = UpdateJournal(root / 'update-state.sqlite', policy, keys=keys)
    original = database.read_bytes()

    def power_loss(*args, **kwargs):
        raise RuntimeError('power loss during package extraction')

    monkeypatch.setattr(installer_module, 'extract_verified_package', power_loss)
    with pytest.raises(RuntimeError):
        install_candidate(root, journal, signed(), package,
                          databases=(database,), now=1500, probe=_healthy)

    assert journal.launch_version() == '0.2.6', '崩溃后不得激活半成品版本'
    assert database.read_bytes() == original, '业务库不得变动'
    assert not (root / 'versions/0.2.7/ZQ技术平台/ZQ技术平台.exe').exists(), \
        '不得残留半成品可执行文件'

    monkeypatch.undo()
    result = install_candidate(root, journal, signed(), package,
                               databases=(database,), now=1600, probe=_healthy)
    assert result.is_file(), '崩溃恢复后重试安装必须成功'
    assert journal.launch_version() == '0.2.7'
    assert database.read_bytes() == original
