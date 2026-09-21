import pytest
from PySide6.QtWidgets import QApplication

from asset_based_agent.technical_platform.session_service import SessionService
from asset_based_agent.technical_platform.store import PlatformStore


def test_drafts_are_independent_persistent_and_not_forked(tmp_path):
    store = PlatformStore(tmp_path / 'state.sqlite', 'alice')
    project = store.create_project('p')
    first, second = store.create_session(project), store.create_session(project)
    service = SessionService(store)
    service.save_draft(first, '第一份草稿', [], submitted=True)
    assert service.draft(second) == {'text': '', 'file_ids': [], 'submitted': False}
    reopened = SessionService(PlatformStore(store.path, 'alice'))
    assert reopened.draft(first) == {'text': '第一份草稿', 'file_ids': [], 'submitted': True}
    store.append(first, 'assistant', 'anchor')
    child = service.fork(first, store.messages(first)[0]['id'], 'child')
    assert service.draft(child) == service.draft(second)
    other = SessionService(PlatformStore(store.path, 'bob'))
    with pytest.raises(PermissionError):
        other.draft(first)
    with pytest.raises(PermissionError):
        other.save_draft(first, 'overwrite', [])
    assert service.draft(first)['text'] == '第一份草稿'


def test_draft_file_scope_and_invalid_input_leave_previous_value(tmp_path):
    store = PlatformStore(tmp_path / 'state.sqlite', 'alice')
    project = store.create_project('p')
    session = store.create_session(project)
    service = SessionService(store)
    service.save_draft(session, 'preserve', [])
    for text, files in [('bad', ['unknown']), ('x' * 12001, []), ('bad', ['same', 'same'])]:
        with pytest.raises((ValueError, PermissionError)):
            service.save_draft(session, text, files)
        assert service.draft(session)['text'] == 'preserve'


def test_window_switch_restores_drafts_and_restart(tmp_path, monkeypatch):
    monkeypatch.setenv('QT_QPA_PLATFORM', 'offscreen')
    from asset_based_agent.technical_platform.app import PlatformWindow
    qt = QApplication.instance() or QApplication([])
    store = PlatformStore(tmp_path / 'state.sqlite', 'alice')
    project = store.create_project('p')
    first, second = store.create_session(project), store.create_session(project)
    window = PlatformWindow(store)
    try:
        window.reload_projects(project)
        window.reload_sessions(first)
        window.composer.setPlainText('draft one')
        window.reload_sessions(second)
        assert window.composer.toPlainText() == ''
        window.composer.setPlainText('draft two')
        window.reload_sessions(first)
        assert window.composer.toPlainText() == 'draft one'
    finally:
        window.close()
    reopened = PlatformWindow(PlatformStore(store.path, 'alice'))
    try:
        reopened.reload_projects(project)
        reopened.reload_sessions(second)
        assert reopened.composer.toPlainText() == 'draft two'
    finally:
        qt.processEvents()
        reopened.close()


def test_project_catalog_drafts_keep_attachment_scope(tmp_path, monkeypatch):
    monkeypatch.setenv('QT_QPA_PLATFORM', 'offscreen')
    from PySide6.QtCore import Qt

    from asset_based_agent.technical_platform.app import PlatformWindow
    from asset_based_agent.technical_platform.project_catalog import ProjectCatalog
    from asset_based_agent.technical_platform.skills import digest
    qt = QApplication.instance() or QApplication([])
    catalog = ProjectCatalog(tmp_path / 'index.sqlite', 'alice')
    projects = []
    for name in ('a', 'b'):
        root = tmp_path / name
        root.mkdir()
        project = catalog.create_project(name, root)
        session = catalog.create_session(project)
        source = root / 'synthetic.txt'
        source.write_text(name, encoding='utf-8')
        file_id = catalog.add_file(project, source, digest(source))
        projects.append((project, session, file_id))
    window = PlatformWindow(catalog)
    try:
        for project, session, file_id in projects:
            window.reload_projects(project)
            window.reload_sessions(session)
            assert window.composer.toPlainText() == ''
            window.composer.setPlainText(project)
            window.files.item(0).setCheckState(Qt.CheckState.Checked)
            assert window.selected_file_ids() == {file_id}
        for project, session, file_id in projects:
            window.reload_projects(project)
            window.reload_sessions(session)
            assert window.composer.toPlainText() == project
            assert window.selected_file_ids() == {file_id}
    finally:
        qt.processEvents()
        window.close()


def test_v6_migration_failure_preserves_v5_and_backup(tmp_path, monkeypatch):
    import sqlite3

    from asset_based_agent.technical_platform import local_migrations as migrations
    store = PlatformStore(tmp_path / 'state.sqlite', 'alice')
    project = store.create_project('p')
    session = store.create_session(project)
    store.append(session, 'user', 'history')
    with store.connect() as db:
        db.execute('DROP TABLE session_drafts')
        db.execute('PRAGMA user_version=5')
    original = migrations.apply_v6
    def fail(db):
        original(db)
        raise RuntimeError('synthetic migration interruption')
    monkeypatch.setattr(migrations, 'apply_v6', fail)
    with pytest.raises(RuntimeError):
        migrations.migrate_database(store.path)
    with store.connect() as db:
        assert db.execute('PRAGMA user_version').fetchone()[0] == 5
        assert db.execute("SELECT name FROM sqlite_master WHERE name='session_drafts'").fetchone() is None
    backup = next((store.path.parent / 'migration-backups').glob('*-v5-*.sqlite'))
    with sqlite3.connect(backup) as db:
        assert db.execute('PRAGMA user_version').fetchone()[0] == 5
        assert db.execute('SELECT text FROM messages').fetchone()[0] == 'history'
    monkeypatch.setattr(migrations, 'apply_v6', original)
    migrations.migrate_database(store.path)
    assert SessionService(store).draft(session)['text'] == ''


def test_failed_save_keeps_input_across_switch_and_refuses_close(tmp_path, monkeypatch):
    monkeypatch.setenv('QT_QPA_PLATFORM', 'offscreen')
    from PySide6.QtGui import QCloseEvent

    from asset_based_agent.technical_platform.app import PlatformWindow
    qt = QApplication.instance() or QApplication([])
    store = PlatformStore(tmp_path / 'state.sqlite', 'alice')
    project = store.create_project('p')
    first, second = store.create_session(project), store.create_session(project)
    window = PlatformWindow(store)
    window.reload_projects(project)
    window.reload_sessions(first)
    original = SessionService.save_draft
    def fail(*args, **kwargs):
        raise OSError('synthetic disk failure')
    monkeypatch.setattr(SessionService, 'save_draft', fail)
    try:
        window.composer.setPlainText('must preserve')
        window.reload_sessions(second)
        window.reload_sessions(first)
        assert window.composer.toPlainText() == 'must preserve'
        event = QCloseEvent()
        window.closeEvent(event)
        assert not event.isAccepted()
        monkeypatch.setattr(SessionService, 'save_draft', original)
        window.closeEvent(event)
        assert event.isAccepted()
        assert SessionService(store).draft(first)['text'] == 'must preserve'
    finally:
        monkeypatch.setattr(SessionService, 'save_draft', original)
        qt.processEvents()
        window.close()
