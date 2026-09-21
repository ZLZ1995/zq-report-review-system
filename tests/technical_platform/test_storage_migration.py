import pytest

from asset_based_agent.technical_platform.storage_preferences import StoragePreferences


def setup(tmp_path):
    program, source, target = (tmp_path / name for name in ('program', 'source', 'target'))
    for path in (program, source, target):
        path.mkdir()
    preferences = StoragePreferences(tmp_path / 'locations.sqlite', program)
    old = preferences.select('alice', source)
    old.prepare()
    (old.credentials / 'synthetic.bin').write_bytes(b'opaque-synthetic-ciphertext')
    return preferences, old, target


def test_migration_preserves_source_and_excludes_other_accounts(tmp_path):
    preferences, old, target = setup(tmp_path)
    other = preferences.select('bob', old.data_root)
    other.prepare()
    (other.downloads / 'private.txt').write_text('other synthetic account')
    new = preferences.migrate('alice', target, confirmed=True, consumers_closed=True)
    assert (new.credentials / 'synthetic.bin').read_bytes() == (old.credentials / 'synthetic.bin').read_bytes()
    assert preferences.load('alice').data_root == target.resolve()
    assert preferences.load('bob').data_root == old.data_root
    assert not list(target.rglob('private.txt'))


@pytest.mark.parametrize('confirmed,closed', [(False, True), (True, False)])
def test_migration_requires_confirmation_and_closed_consumers(tmp_path, confirmed, closed):
    preferences, old, target = setup(tmp_path)
    with pytest.raises(PermissionError):
        preferences.migrate('alice', target, confirmed=confirmed, consumers_closed=closed)
    assert preferences.load('alice').data_root == old.data_root
    assert not list(target.iterdir())


def test_copy_failure_keeps_old_selection(tmp_path, monkeypatch):
    import shutil
    preferences, old, target = setup(tmp_path)
    def fail(*args, **kwargs):
        raise OSError('synthetic disk full')
    monkeypatch.setattr(shutil, 'copyfile', fail)
    with pytest.raises(OSError):
        preferences.migrate('alice', target, confirmed=True, consumers_closed=True)
    assert preferences.load('alice').data_root == old.data_root
    assert (old.credentials / 'synthetic.bin').is_file()


def test_target_collision_never_overwrites_existing_account(tmp_path):
    from asset_based_agent.technical_platform.storage_layout import StorageLayout
    preferences, old, target = setup(tmp_path)
    destination = StorageLayout(preferences.program_root, target, 'alice')
    destination.prepare()
    marker = destination.credentials / 'keep'
    marker.write_bytes(b'keep')
    with pytest.raises(ValueError):
        preferences.migrate('alice', target, confirmed=True, consumers_closed=True)
    assert marker.read_bytes() == b'keep'
    assert preferences.load('alice').data_root == old.data_root


def test_source_change_during_copy_does_not_activate_destination(tmp_path, monkeypatch):
    import shutil
    preferences, old, target = setup(tmp_path)
    copy = shutil.copyfile
    def changed(source, destination):
        result = copy(source, destination)
        source.write_bytes(b'changed during migration')
        return result
    monkeypatch.setattr(shutil, 'copyfile', changed)
    with pytest.raises(ValueError, match='source changed'):
        preferences.migrate('alice', target, confirmed=True, consumers_closed=True)
    assert preferences.load('alice').data_root == old.data_root


def test_live_data_lease_blocks_migration_even_with_closed_claim(tmp_path):
    import sqlite3
    preferences, old, target = setup(tmp_path)
    with preferences.use('alice') as leased:
        assert leased.data_root == old.data_root
        with pytest.raises(sqlite3.OperationalError, match='locked'):
            preferences.migrate('alice', target, confirmed=True, consumers_closed=True)
        assert not list(target.iterdir())
    new = preferences.migrate('alice', target, confirmed=True, consumers_closed=True)
    assert new.data_root == target.resolve()


def test_data_leases_allow_simultaneous_readers(tmp_path):
    preferences, old, _ = setup(tmp_path)
    second = StoragePreferences(preferences.index_path, preferences.program_root)
    with preferences.use('alice') as first, second.use('alice') as other:
        assert first.data_root == other.data_root == old.data_root


def test_missing_account_tree_is_not_assumed_empty_and_switched(tmp_path):
    program, source, target = (tmp_path / name for name in ('program', 'source', 'target'))
    for path in (program, source, target):
        path.mkdir()
    preferences = StoragePreferences(tmp_path / 'locations.sqlite', program)
    preferences.select('alice', source)
    with pytest.raises(ValueError, match='missing'):
        preferences.migrate('alice', target, confirmed=True, consumers_closed=True)
    assert preferences.load('alice').data_root == source.resolve()
    assert not list(source.iterdir())
    assert not list(target.iterdir())


def test_lease_blocks_migration_from_another_process(tmp_path):
    import subprocess
    import sys
    preferences, old, target = setup(tmp_path)
    code = '''
import sqlite3, sys
from pathlib import Path
from asset_based_agent.technical_platform.storage_preferences import StoragePreferences
p = StoragePreferences(Path(sys.argv[1]), Path(sys.argv[2]))
try:
    p.migrate('alice', Path(sys.argv[3]), confirmed=True, consumers_closed=True)
except sqlite3.OperationalError as exc:
    assert 'locked' in str(exc)
    sys.exit(0)
sys.exit(7)
'''
    with preferences.use('alice'):
        result = subprocess.run(
            [sys.executable, '-c', code, str(preferences.index_path),
             str(preferences.program_root), str(target)],
            capture_output=True, text=True, timeout=15, check=False,
        )
        assert result.returncode == 0, result.stderr
    assert preferences.load('alice').data_root == old.data_root
    assert not list(target.iterdir())


def test_wal_index_cannot_bypass_reader_exclusion(tmp_path):
    import sqlite3
    from contextlib import closing
    preferences, old, target = setup(tmp_path)
    with closing(sqlite3.connect(preferences.index_path)) as db:
        assert db.execute('PRAGMA journal_mode=WAL').fetchone()[0] == 'wal'
    with pytest.raises(ValueError, match='journaling'), preferences.use('alice'):
        pytest.fail('WAL lease must not be granted')
    with pytest.raises(ValueError, match='journaling'):
        preferences.migrate('alice', target, confirmed=True, consumers_closed=True)
    assert preferences.load('alice').data_root == old.data_root
    assert not list(target.iterdir())


@pytest.mark.parametrize('permanent', [False, True])
def test_windows_rename_contention_is_bounded_and_never_switches_early(tmp_path, monkeypatch, permanent):
    from pathlib import Path

    preferences, old, target = setup(tmp_path)
    original = Path.rename
    calls = []
    def rename(stage, destination):
        calls.append(stage)
        if permanent or len(calls) < 3:
            error = PermissionError('synthetic rename contention')
            error.winerror = 5
            raise error
        return original(stage, destination)
    monkeypatch.setattr(Path, 'rename', rename)
    if permanent:
        with pytest.raises(PermissionError):
            preferences.migrate('alice', target, confirmed=True, consumers_closed=True)
        assert preferences.load('alice').data_root == old.data_root
        assert len(calls) == 4
        assert calls[-1].is_dir()
    else:
        new = preferences.migrate('alice', target, confirmed=True, consumers_closed=True)
        assert preferences.load('alice').data_root == target.resolve()
        assert (new.credentials / 'synthetic.bin').read_bytes() == (old.credentials / 'synthetic.bin').read_bytes()
        assert len(calls) == 3


@pytest.mark.parametrize('change', ['destination', 'staging'])
def test_rename_retry_revalidates_content_and_target(tmp_path, monkeypatch, change):
    from pathlib import Path

    preferences, old, target = setup(tmp_path)
    calls = []
    def rename(stage, destination):
        calls.append(stage)
        if change == 'destination':
            destination.mkdir()
            (destination / 'keep').write_bytes(b'other content')
        else:
            (stage / 'unexpected').write_bytes(b'changed staging')
        error = PermissionError('synthetic contention with mutation')
        error.winerror = 32
        raise error
    monkeypatch.setattr(Path, 'rename', rename)
    with pytest.raises(ValueError, match='changed'):
        preferences.migrate('alice', target, confirmed=True, consumers_closed=True)
    assert len(calls) == 1
    assert preferences.load('alice').data_root == old.data_root
    assert (old.credentials / 'synthetic.bin').read_bytes() == b'opaque-synthetic-ciphertext'
