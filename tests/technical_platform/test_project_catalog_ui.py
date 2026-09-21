import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from asset_based_agent.technical_platform.app import PlatformWindow
from asset_based_agent.technical_platform.project_catalog import ProjectCatalog


def test_closed_project_releases_sqlite_connections_before_move(tmp_path, monkeypatch):
    import sqlite3

    app = QApplication.instance() or QApplication([])
    assert app
    connect = sqlite3.connect
    opened = set()

    class TrackedConnection(sqlite3.Connection):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            opened.add(id(self))

        def close(self):
            super().close()
            opened.discard(id(self))

    def tracked_connect(*args, **kwargs):
        return connect(*args, **kwargs, factory=TrackedConnection)

    monkeypatch.setattr(sqlite3, 'connect', tracked_connect)
    for index in range(10):
        root = tmp_path / f'project-{index}'
        root.mkdir()
        catalog = ProjectCatalog(tmp_path / f'index-{index}.sqlite', 'alice')
        project = catalog.create_project('project', root)
        session = catalog.create_session(project, 'first')
        catalog.remember_session(session)
        window = PlatformWindow(ProjectCatalog(catalog.index_path, 'alice'))
        try:
            assert window.session_id == session
            app.processEvents()
            assert not opened, 'Database connection escaped its operation'
        finally:
            window.close()
        assert not window.session_badge_timer.isActive()
        assert not opened, 'Database connection remained open after window close'
        root.rename(tmp_path / f'moved-{index}')


def test_reopen_restores_selected_session_and_missing_project_is_nonblocking(tmp_path, monkeypatch):
    monkeypatch.setenv("SystemDrive", "Z:")
    app = QApplication.instance() or QApplication([])
    assert app
    root = tmp_path / "project"
    root.mkdir()
    catalog = ProjectCatalog(tmp_path / "settings.sqlite", "alice")
    project = catalog.create_project("project", root)
    first = catalog.create_session(project, "first")
    catalog.create_session(project, "second")
    catalog.remember_session(first)
    window = PlatformWindow(ProjectCatalog(catalog.index_path, "alice"))
    assert window.project_id == project
    assert window.session_id == first
    window.close()
    try:
        root.rename(tmp_path / "moved")
    except PermissionError:
        from scripts.windows_file_owners import file_owners
        try:
            print('RENAME_FILE_OWNERS', file_owners(list(root.rglob('*.sqlite'))))
        except (OSError, ValueError) as diagnostic_error:
            print('RENAME_DIAGNOSTIC_ERROR', repr(diagnostic_error))
        print('RENAME_PROCESS', os.getpid(), 'TIMER_ACTIVE', window.session_badge_timer.isActive())
        raise
    missing = PlatformWindow(ProjectCatalog(catalog.index_path, "alice"))
    assert missing.project_id is None
    assert "目录不可用" in missing.status.text()
    missing.close()
