import hashlib
import sqlite3
from contextlib import closing

import pytest

from asset_based_agent.technical_platform.updates.database_backup import (
    backup_database,
    restore_database_copy,
)


def test_backup_includes_committed_wal_and_restore_never_overwrites_original(tmp_path):
    original = tmp_path / 'project.sqlite'
    folder = tmp_path / 'backups'
    folder.mkdir()
    with closing(sqlite3.connect(original)) as live:
        live.execute('PRAGMA journal_mode=WAL')
        live.execute('CREATE TABLE messages(body TEXT)')
        live.execute("INSERT INTO messages VALUES('synthetic history')")
        live.commit()
        snapshot = backup_database(original, folder)
        assert snapshot.path.parent == folder
        with closing(sqlite3.connect(snapshot.path)) as backup:
            assert backup.execute('SELECT body FROM messages').fetchone()[0] == 'synthetic history'
        restored = tmp_path / 'restored.sqlite'
        restore_database_copy(snapshot, restored)
        with closing(sqlite3.connect(restored)) as copied:
            assert copied.execute('SELECT body FROM messages').fetchone()[0] == 'synthetic history'
        with pytest.raises(FileExistsError):
            restore_database_copy(snapshot, original)
        assert live.execute('SELECT count(*) FROM messages').fetchone()[0] == 1


def test_damaged_backup_is_rejected_before_creating_restore_copy(tmp_path):
    source = tmp_path / 'project.sqlite'
    with closing(sqlite3.connect(source)) as db:
        db.execute('CREATE TABLE test(a)')
    backups = tmp_path / 'backups'
    backups.mkdir()
    saved = backup_database(source, backups)
    saved.path.write_bytes(b'tampered')
    output = tmp_path / 'restore.sqlite'
    with pytest.raises(ValueError):
        restore_database_copy(saved, output)
    assert not output.exists()


def test_missing_or_invalid_source_never_produces_valid_snapshot(tmp_path):
    with pytest.raises(FileNotFoundError):
        backup_database(tmp_path / 'missing.sqlite', tmp_path)
    source = tmp_path / 'bad.sqlite'
    source.write_bytes(b'not a database')
    original_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    with pytest.raises(ValueError):
        backup_database(source, tmp_path)
    assert hashlib.sha256(source.read_bytes()).hexdigest() == original_hash

