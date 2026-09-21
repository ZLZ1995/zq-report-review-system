import base64
import hashlib
import json
import sqlite3
import zipfile
from contextlib import closing

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from asset_based_agent.technical_platform.updates.installer import install_candidate
from asset_based_agent.technical_platform.updates.journal import UpdateJournal
from asset_based_agent.technical_platform.updates.manifest import (
    DOMAIN,
    UpdatePolicy,
    canonical_payload,
)
from asset_based_agent.technical_platform.updates.process_lock import InstallationLock


@pytest.fixture
def fixture(tmp_path):
    root = tmp_path / 'installation'
    root.mkdir()
    (root / 'versions').mkdir()
    old = root / 'versions/0.2.6'
    old.mkdir()
    (old / 'old.exe').write_bytes(b'old')
    key = Ed25519PrivateKey.generate()
    keys = {'test': key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)}
    policy = UpdatePolicy('0.2.6', 9, 'windows', 'x86_64', 1, 10, '1.0.0', frozenset({'releases.test'}))
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
        payload = {'schema_version': 1, 'key_id': 'test', 'sequence': seq, 'version': version,
                   'platform': 'windows', 'arch': 'x86_64', 'url': 'https://releases.test/app.zip',
                   'size': package.stat().st_size, 'sha256': hashlib.sha256(package.read_bytes()).hexdigest(),
                   'protocol_min': 1, 'protocol_max': 1, 'data_schema_min': 1, 'data_schema_max': 30,
                   'minimum_updater': '1.0.0', 'issued_at': 1000, 'expires_at': 2000, 'notes': 'test'}
        return json.dumps({'payload': payload, 'signature': base64.b64encode(
            key.sign(DOMAIN + canonical_payload(payload))).decode()}).encode()
    return root, policy, keys, database, package, signed


def test_installation_preserves_history_and_previous_version(fixture):
    root, policy, keys, database, package, signed = fixture
    journal = UpdateJournal(root / 'update-state.sqlite', policy, keys=keys)
    original = database.read_bytes()
    def health(executable, work, release):
        assert executable.is_file()
        assert list((root / 'backups').rglob('*.sqlite'))
        return {'client_version': release.version, 'protocol_version': 1, 'local_schema_version': 10}
    for version, sequence in [('0.2.7', 10), ('0.2.8', 11)]:
        result = install_candidate(root, journal, signed(version, sequence), package,
                                   databases=(database,), now=1500, probe=health)
        assert result.is_file()
        assert journal.launch_version() == version
        assert database.read_bytes() == original
    assert (root / 'versions/0.2.6/old.exe').read_bytes() == b'old'


def test_additive_schema_upgrade_accepts_candidate_within_signed_range(fixture):
    root, policy, keys, database, package, signed = fixture
    journal = UpdateJournal(root / 'update-state.sqlite', policy, keys=keys)
    original = database.read_bytes()

    def health(_executable, _work, release):
        return {'client_version': release.version, 'protocol_version': 1,
                'local_schema_version': 11}

    result = install_candidate(root, journal, signed(), package,
                               databases=(database,), now=1500, probe=health)
    assert result.is_file()
    assert journal.launch_version() == '0.2.7'
    assert database.read_bytes() == original


def test_webengine_helper_executable_is_not_treated_as_client_entrypoint(fixture):
    root, policy, keys, database, package, signed = fixture
    with zipfile.ZipFile(package, 'a') as archive:
        archive.writestr(
            'ZQ技术平台/_internal/PySide6/QtWebEngineProcess.exe',
            b'synthetic webengine helper',
        )
    journal = UpdateJournal(root / 'update-state.sqlite', policy, keys=keys)

    def health(executable, _work, release):
        assert executable.name == 'ZQ技术平台.exe'
        assert executable.parent.name == 'ZQ技术平台'
        return {'client_version': release.version, 'protocol_version': 1,
                'local_schema_version': 10}

    result = install_candidate(
        root, journal, signed(), package,
        databases=(database,), now=1500, probe=health,
    )
    assert result.name == 'ZQ技术平台.exe'
    assert journal.launch_version() == '0.2.7'


@pytest.mark.parametrize('candidate_schema', [9, 31])
def test_candidate_schema_outside_safe_signed_range_is_rejected(
        fixture, candidate_schema):
    root, policy, keys, database, package, signed = fixture
    journal = UpdateJournal(root / 'update-state.sqlite', policy, keys=keys)

    def health(_executable, _work, release):
        return {'client_version': release.version, 'protocol_version': 1,
                'local_schema_version': candidate_schema}

    with pytest.raises(ValueError, match='schema'):
        install_candidate(root, journal, signed(), package,
                          databases=(database,), now=1500, probe=health)


def test_failed_candidate_is_not_selected_and_requires_recovery(fixture):
    root, policy, keys, database, package, signed = fixture
    journal = UpdateJournal(root / 'update-state.sqlite', policy, keys=keys)
    def failed(*_):
        raise RuntimeError('synthetic health failure')
    with pytest.raises(RuntimeError):
        install_candidate(root, journal, signed(), package, databases=(database,), now=1500, probe=failed)
    assert journal.snapshot()['active_version'] == '0.2.6'
    assert journal.snapshot()['phase'] == 'recovery_required'
    with pytest.raises(ValueError):
        journal.launch_version()


def test_live_runtime_prevents_any_installation_write(fixture):
    root, policy, keys, database, package, signed = fixture
    journal = UpdateJournal(root / 'update-state.sqlite', policy, keys=keys)
    with InstallationLock(root / 'installation-lock.sqlite').runtime(), pytest.raises(BlockingIOError):
        install_candidate(root, journal, signed(), package, databases=(database,), now=1500)
    assert journal.launch_version() == '0.2.6'
    assert not (root / 'backups').exists()


def test_failed_readonly_health_can_recover_without_replacing_user_data(fixture):
    from asset_based_agent.technical_platform.updates.installer import recover_unchanged

    root, policy, keys, database, package, signed = fixture
    journal = UpdateJournal(root / 'update-state.sqlite', policy, keys=keys)
    def failed(*_):
        raise RuntimeError('synthetic failure')
    with pytest.raises(RuntimeError):
        install_candidate(root, journal, signed(), package, databases=(database,), now=1500, probe=failed)
    original = database.read_bytes()
    recover_unchanged(root, journal)
    assert journal.launch_version() == '0.2.6'
    assert database.read_bytes() == original
    assert not (root / 'versions/0.2.7').exists()
    assert list((root / 'failed-versions').iterdir())


def test_recovery_never_discards_new_user_writes(fixture):
    from asset_based_agent.technical_platform.updates.installer import recover_unchanged

    root, policy, keys, database, package, signed = fixture
    journal = UpdateJournal(root / 'update-state.sqlite', policy, keys=keys)
    def failed(*_):
        raise RuntimeError('synthetic failure')
    with pytest.raises(RuntimeError):
        install_candidate(root, journal, signed(), package, databases=(database,), now=1500, probe=failed)
    with closing(sqlite3.connect(database)) as db, db:
        db.execute("INSERT INTO messages VALUES('new user write')")
    with pytest.raises(ValueError):
        recover_unchanged(root, journal)
    with closing(sqlite3.connect(database)) as db:
        assert db.execute('SELECT count(*) FROM messages').fetchone()[0] == 2
    assert journal.snapshot()['phase'] == 'recovery_required'


def test_recovery_handles_process_loss_before_failure_is_recorded(fixture, monkeypatch):
    from asset_based_agent.technical_platform.updates.installer import recover_unchanged

    root, policy, keys, database, package, signed = fixture
    journal = UpdateJournal(root / 'update-state.sqlite', policy, keys=keys)
    # Model abrupt process loss: the durable activating transition exists, but
    # the exception handler never persists its failure transition.
    monkeypatch.setattr(journal, 'fail', lambda _: None)
    def interrupted(*_):
        raise RuntimeError('process lost before failure journal write')
    original = database.read_bytes()
    with pytest.raises(RuntimeError):
        install_candidate(root, journal, signed(), package, databases=(database,), now=1500, probe=interrupted)
    reopened = UpdateJournal(root / 'update-state.sqlite', policy, keys=keys)
    assert reopened.snapshot()['phase'] == 'activating'
    recover_unchanged(root, reopened)
    assert reopened.launch_version() == '0.2.6'
    assert database.read_bytes() == original
