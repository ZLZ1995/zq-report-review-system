import json
import sqlite3

import pytest

from asset_based_agent.technical_platform.store import PlatformStore


def setup(tmp_path):
    from asset_based_agent.technical_platform.session_service import SessionService
    store = PlatformStore(tmp_path / 'state.sqlite', 'alice')
    project = store.create_project('project')
    session = store.create_session(project)
    return store, project, session, SessionService(store)


def test_rename_archive_restore_and_owner_isolation(tmp_path):
    store, project, session, service = setup(tmp_path)
    service.rename(session, '  新标题  ')
    assert store.session(session)['title'] == '新标题'
    service.archive(session, True)
    assert store.sessions(project) == []
    with pytest.raises(ValueError, match='归档'):
        store.start_run(session, {})
    assert service.list(project, archived=True)[0]['id'] == session
    service.archive(session, False)
    assert store.sessions(project)[0]['id'] == session
    from asset_based_agent.technical_platform.session_service import SessionService
    other = SessionService(PlatformStore(store.path, 'bob'))
    for call in (lambda: other.rename(session, 'bad'), lambda: other.archive(session, True),
                 lambda: other.list(project)):
        with pytest.raises(PermissionError):
            call()
    with pytest.raises(ValueError):
        service.rename(session, ' ')
    run = store.start_run(session, {})
    with pytest.raises(ValueError):
        service.archive(session, True)
    store.transition(run, 'failed', 'synthetic')
    service.archive(session, True)


def test_read_cursor_is_monotonic_and_bound_to_session(tmp_path):
    store, project, session, service = setup(tmp_path)
    store.append(session, 'assistant', 'one')
    store.append(session, 'assistant', 'two')
    first, second = store.messages(session)
    assert service.list(project)[0]['unread_count'] == 2
    service.mark_read(session, second['id'])
    service.mark_read(session, first['id'])
    assert service.list(project)[0]['last_read_message'] == second['id']
    assert service.list(project)[0]['unread_count'] == 0
    other = store.create_session(project)
    store.append(other, 'assistant', 'not yours')
    with pytest.raises(PermissionError):
        service.mark_read(session, store.messages(other)[0]['id'])


def test_fork_records_anchor_without_copying_actions_permissions_or_attachments(tmp_path):
    store, project, session, service = setup(tmp_path)
    store.append(session, 'user', '只读审核，不修改原文件')
    message = store.messages(session)[0]
    child = service.fork(session, message['id'], '新分支')
    row = next(item for item in service.list(project) if item['id'] == child)
    assert row['parent_session'] == session and row['fork_message'] == message['id']
    snapshot = json.loads(row['context_snapshot'])
    assert snapshot['source_message']['id'] == message['id']
    assert len(snapshot['source_message']['sha256']) == 64
    assert snapshot['completed_facts'] == []
    assert store.messages(child) == [] and store.runs(child) == []
    with store.connect() as db:
        assert db.execute('SELECT COUNT(*) FROM conversation_state WHERE session=?', (child,)).fetchone()[0] == 0
        assert db.execute('SELECT COUNT(*) FROM execution_authorizations').fetchone()[0] == 0
    with pytest.raises(PermissionError):
        service.fork(child, message['id'], 'wrong anchor')
    reopened = type(service)(PlatformStore(store.path, 'alice'))
    assert next(item for item in reopened.list(project) if item['id'] == child)['context_snapshot'] == row['context_snapshot']


def test_v4_migration_preserves_history_and_has_original_backup(tmp_path):
    from asset_based_agent.technical_platform.local_migrations import migrate_database
    store, _, session, _ = setup(tmp_path)
    store.append(session, 'assistant', 'preserved')
    with store.connect() as db:
        db.execute('DROP TABLE session_metadata')
        db.execute('PRAGMA user_version=4')
    backup = migrate_database(store.path)
    assert backup is not None
    with sqlite3.connect(backup) as db:
        assert db.execute('PRAGMA user_version').fetchone()[0] == 4
        assert db.execute('SELECT text FROM messages').fetchone()[0] == 'preserved'
    assert store.messages(session)[0]['text'] == 'preserved'


def test_v5_migration_failure_restores_v4_without_partial_table(tmp_path, monkeypatch):
    from asset_based_agent.technical_platform import local_migrations as migrations
    store, _, session, _ = setup(tmp_path)
    store.append(session, 'assistant', 'preserved')
    with store.connect() as db:
        db.execute('DROP TABLE session_metadata')
        db.execute('PRAGMA user_version=4')
    def fail(db):
        db.execute('CREATE TABLE partial_metadata(id TEXT)')
        raise RuntimeError('synthetic migration failure')
    monkeypatch.setattr(migrations, 'apply_v5', fail)
    with pytest.raises(RuntimeError, match='synthetic'):
        migrations.migrate_database(store.path)
    with store.connect() as db:
        assert db.execute('PRAGMA user_version').fetchone()[0] == 4
        assert db.execute("SELECT name FROM sqlite_master WHERE name='partial_metadata'").fetchone() is None
        assert db.execute('SELECT text FROM messages').fetchone()[0] == 'preserved'
