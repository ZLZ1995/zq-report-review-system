"""Legacy metadata migration is transactional and backed up before schema writes."""
import sqlite3

import pytest


def legacy(path):
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE sample(id INTEGER PRIMARY KEY, value TEXT)')
        db.execute('INSERT INTO sample(value) VALUES(?)', ('preserve-me',))


def test_migration_preserves_legacy_and_creates_one_consistent_backup(tmp_path):
    from asset_based_agent.technical_platform.local_migrations import migrate_database
    path = tmp_path / 'platform.sqlite'
    legacy(path)
    backup = migrate_database(path)
    assert backup.is_file()
    with sqlite3.connect(backup) as db:
        assert db.execute('PRAGMA user_version').fetchone()[0] == 0
        assert db.execute('SELECT value FROM sample').fetchone()[0] == 'preserve-me'
    with sqlite3.connect(path) as db:
        from asset_based_agent.technical_platform.local_migrations import SCHEMA_VERSION
        assert db.execute('PRAGMA user_version').fetchone()[0] == SCHEMA_VERSION
        assert db.execute('SELECT value FROM sample').fetchone()[0] == 'preserve-me'
    assert migrate_database(path) is None
    assert len(list(backup.parent.glob('*.sqlite'))) == 1


def test_future_schema_rejected_without_mutation(tmp_path):
    from asset_based_agent.technical_platform.local_migrations import migrate_database
    path = tmp_path / 'future.sqlite'
    legacy(path)
    with sqlite3.connect(path) as db:
        db.execute('PRAGMA user_version=999')
    before = path.read_bytes()
    with pytest.raises(ValueError, match='schema'):
        migrate_database(path)
    assert path.read_bytes() == before
    assert not (tmp_path / 'migration-backups').exists()


def test_v8_upgrade_adds_upload_attempts_and_preserves_backup(tmp_path):
    from asset_based_agent.technical_platform.local_migrations import migrate_database
    path = tmp_path / 'v8.sqlite'
    legacy(path)
    with sqlite3.connect(path) as db:
        db.execute('PRAGMA user_version=8')
    backup = migrate_database(path)
    with sqlite3.connect(backup) as db:
        assert db.execute('PRAGMA user_version').fetchone()[0] == 8
        assert db.execute('SELECT value FROM sample').fetchone()[0] == 'preserve-me'
    with sqlite3.connect(path) as db:
        from asset_based_agent.technical_platform.local_migrations import SCHEMA_VERSION
        assert db.execute('PRAGMA user_version').fetchone()[0] == SCHEMA_VERSION
        assert db.execute('SELECT COUNT(*) FROM browser_upload_attempts').fetchone()[0] == 0


def test_v3_upgrade_preserves_backup_and_creates_step_results(tmp_path):
    from asset_based_agent.technical_platform.local_migrations import migrate_database
    path = tmp_path / 'v3.sqlite'
    legacy(path)
    with sqlite3.connect(path) as db:
        db.execute('PRAGMA user_version=3')
    backup = migrate_database(path)
    assert backup is not None and '-v3-' in backup.name
    with sqlite3.connect(backup) as db:
        assert db.execute('PRAGMA user_version').fetchone()[0] == 3
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT COUNT(*) FROM execution_results').fetchone()[0] == 0


def test_v1_upgrade_backs_up_actual_version_and_adds_execution_tables(tmp_path):
    from asset_based_agent.technical_platform.local_migrations import migrate_database
    path = tmp_path / 'v1.sqlite'
    legacy(path)
    with sqlite3.connect(path) as db:
        db.execute('PRAGMA user_version=1')
    backup = migrate_database(path)
    assert backup is not None and '-v1-' in backup.name
    with sqlite3.connect(backup) as db:
        assert db.execute('PRAGMA user_version').fetchone()[0] == 1
    with sqlite3.connect(path) as db:
        from asset_based_agent.technical_platform.local_migrations import SCHEMA_VERSION
        assert db.execute('PRAGMA user_version').fetchone()[0] == SCHEMA_VERSION
        names = {row[0] for row in db.execute('SELECT name FROM sqlite_master')}
        assert {'execution_plans', 'execution_steps', 'execution_events'} <= names
        assert db.execute('SELECT value FROM sample').fetchone()[0] == 'preserve-me'


def test_v2_failure_preserves_v1_and_rolls_back_ddl(tmp_path, monkeypatch):
    from asset_based_agent.technical_platform import local_migrations as migrations
    path = tmp_path / 'v1.sqlite'
    legacy(path)
    with sqlite3.connect(path) as db:
        db.execute('PRAGMA user_version=1')

    def fail(db):
        db.execute('CREATE TABLE partial_upgrade(id INTEGER)')
        raise RuntimeError('v2-failure')

    monkeypatch.setattr(migrations, 'apply_v2', fail)
    with pytest.raises(RuntimeError, match='v2-failure'):
        migrations.migrate_database(path)
    with sqlite3.connect(path) as db:
        assert db.execute('PRAGMA user_version').fetchone()[0] == 1
        assert db.execute("SELECT name FROM sqlite_master WHERE name='partial_upgrade'").fetchone() is None
    assert len(list((tmp_path / 'migration-backups').glob('*-v1-*.sqlite'))) == 1


def test_new_store_has_execution_tables(tmp_path):
    from asset_based_agent.technical_platform.store import PlatformStore
    store = PlatformStore(tmp_path / 'new.sqlite', 'alice')
    with store.connect() as db:
        assert db.execute('SELECT COUNT(*) FROM execution_events').fetchone()[0] == 0
        from asset_based_agent.technical_platform.local_migrations import SCHEMA_VERSION
        assert db.execute('PRAGMA user_version').fetchone()[0] == SCHEMA_VERSION


def test_v2_upgrade_preserves_backup_and_adds_authorizations(tmp_path):
    from asset_based_agent.technical_platform.local_migrations import migrate_database
    path = tmp_path / 'v2.sqlite'
    legacy(path)
    with sqlite3.connect(path) as db:
        db.execute('PRAGMA user_version=2')
    backup = migrate_database(path)
    assert backup is not None and '-v2-' in backup.name
    with sqlite3.connect(backup) as db:
        assert db.execute('PRAGMA user_version').fetchone()[0] == 2
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT COUNT(*) FROM execution_authorizations').fetchone()[0] == 0


def test_v3_failure_keeps_v2_usable(tmp_path, monkeypatch):
    from asset_based_agent.technical_platform import local_migrations as migrations
    path = tmp_path / 'v2.sqlite'
    legacy(path)
    with sqlite3.connect(path) as db:
        db.execute('PRAGMA user_version=2')
    def fail(db):
        db.execute('CREATE TABLE partial_v3(id INTEGER)')
        raise RuntimeError('v3-failure')
    monkeypatch.setattr(migrations, 'apply_v3', fail)
    with pytest.raises(RuntimeError, match='v3-failure'):
        migrations.migrate_database(path)
    with sqlite3.connect(path) as db:
        assert db.execute('PRAGMA user_version').fetchone()[0] == 2
        assert db.execute("SELECT name FROM sqlite_master WHERE name='partial_v3'").fetchone() is None
        assert db.execute('SELECT value FROM sample').fetchone()[0] == 'preserve-me'


def test_migration_failure_rolls_back_and_preserves_backup(tmp_path, monkeypatch):
    from asset_based_agent.technical_platform import local_migrations as migrations
    path = tmp_path / 'platform.sqlite'
    legacy(path)

    def fail(db):
        db.execute('CREATE TABLE should_rollback(id INTEGER)')
        raise RuntimeError('synthetic-failure')

    monkeypatch.setattr(migrations, 'apply_v1', fail)
    with pytest.raises(RuntimeError, match='synthetic-failure'):
        migrations.migrate_database(path)
    with sqlite3.connect(path) as db:
        assert db.execute('PRAGMA user_version').fetchone()[0] == 0
        assert db.execute("SELECT name FROM sqlite_master WHERE name='should_rollback'").fetchone() is None
        assert db.execute('SELECT value FROM sample').fetchone()[0] == 'preserve-me'
    assert len(list((tmp_path / 'migration-backups').glob('*.sqlite'))) == 1


def test_missing_database_is_not_recreated(tmp_path):
    from asset_based_agent.technical_platform.local_migrations import migrate_database
    path = tmp_path / 'missing.sqlite'
    with pytest.raises(OSError):
        migrate_database(path)
    assert not path.exists()


def test_store_rejects_future_database_before_bootstrapping_tables(tmp_path):
    from asset_based_agent.technical_platform.store import PlatformStore
    path = tmp_path / 'future.sqlite'
    legacy(path)
    with sqlite3.connect(path) as db:
        db.execute('PRAGMA user_version=999')
    with pytest.raises(ValueError, match='schema'):
        PlatformStore(path, 'alice', create=False)
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT name FROM sqlite_master WHERE name='projects'").fetchone() is None


def test_active_task_prevents_migration(tmp_path):
    from asset_based_agent.technical_platform.local_migrations import migrate_database
    path = tmp_path / 'active.sqlite'
    legacy(path)
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE runs(state TEXT)')
        db.execute("INSERT INTO runs VALUES('running')")
    before = path.read_bytes()
    with pytest.raises(ValueError, match='active tasks'):
        migrate_database(path)
    assert path.read_bytes() == before
    assert not (tmp_path / 'migration-backups').exists()


def test_concurrent_openers_create_only_one_backup(tmp_path):
    from concurrent.futures import ThreadPoolExecutor

    from asset_based_agent.technical_platform.local_migrations import migrate_database
    path = tmp_path / 'concurrent.sqlite'
    legacy(path)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(migrate_database, [path, path]))
    assert sum(result is not None for result in results) == 1
    assert len(list((tmp_path / 'migration-backups').glob('*.sqlite'))) == 1


def test_backup_directory_failure_leaves_database_unchanged(tmp_path):
    from asset_based_agent.technical_platform.local_migrations import migrate_database
    path = tmp_path / 'blocked.sqlite'
    legacy(path)
    (tmp_path / 'migration-backups').write_text('not a directory', encoding='utf-8')
    before = path.read_bytes()
    with pytest.raises(OSError):
        migrate_database(path)
    assert path.read_bytes() == before


def test_real_legacy_store_preserves_all_existing_rows_and_attachment(tmp_path):
    from hashlib import sha256

    from asset_based_agent.technical_platform.store import PlatformStore
    path = tmp_path / 'legacy.sqlite'
    store = PlatformStore(path, 'alice')
    project = store.create_project('migration fixture')
    session = store.create_session(project)
    store.append(session, 'user', 'synthetic history')
    store.remember(project, 'synthetic preference', confirmed=True)
    attachment = tmp_path / 'synthetic.txt'
    attachment.write_text('synthetic attachment', encoding='utf-8')
    digest = sha256(attachment.read_bytes()).hexdigest()
    store.add_file(project, attachment, digest)
    run = store.start_run(session, {'selected_files': [], 'permissions': {}})
    store.transition(run, 'running', 'start')
    store.transition(run, 'validating', 'check')
    store.transition(run, 'succeeded', 'done')
    with sqlite3.connect(path) as db:
        db.execute('DROP TABLE conversation_state')
        db.execute('PRAGMA user_version=0')
        before = list(db.iterdump())
    reopened = PlatformStore(path, 'alice', create=False)
    assert reopened.messages(session) == store.messages(session)
    assert sha256(attachment.read_bytes()).hexdigest() == digest
    backup = next((tmp_path / 'migration-backups').glob('*.sqlite'))
    with sqlite3.connect(backup) as db:
        assert list(db.iterdump()) == before
    with sqlite3.connect(path) as db:
        existing_inserts = [row for row in db.iterdump() if row.startswith('INSERT INTO')]
    assert existing_inserts == [row for row in before if row.startswith('INSERT INTO')]
