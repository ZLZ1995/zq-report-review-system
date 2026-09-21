import os
from threading import Event
from types import SimpleNamespace

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtWidgets import QApplication

from asset_based_agent.technical_platform.app import PlatformWindow
from asset_based_agent.technical_platform.store import PlatformStore
from asset_based_agent.technical_platform.task_manager import TaskBinding


def test_session_actions_rename_archive_restore_and_guard(tmp_path, monkeypatch):
    from asset_based_agent.technical_platform import app as ui
    qt = QApplication.instance() or QApplication([])
    store = PlatformStore(tmp_path / 'state.sqlite', 'alice')
    project = store.create_project('project')
    session = store.create_session(project, 'original')
    window = PlatformWindow(store)
    window.reload_projects(project)
    try:
        monkeypatch.setattr(ui.QInputDialog, 'getText', lambda *args, **kwargs: ('renamed', True))
        window.rename_session()
        assert store.session(session)['title'] == 'renamed'
        assert window.session_id == session
        worker = SimpleNamespace(cancel=Event(), isRunning=lambda: True)
        binding = TaskBinding('alice', project, session, 'understanding:test')
        window.task_manager.register(binding, worker)
        window.archive_session()
        assert store.sessions(project)[0]['id'] == session
        worker.isRunning = lambda: False
        window.task_manager.finish(binding, worker)
        monkeypatch.setattr(ui.QMessageBox, 'question', lambda *args: ui.QMessageBox.StandardButton.Yes)
        window.archive_session()
        assert store.sessions(project) == []
        assert window.session_id is None
        monkeypatch.setattr(ui.QInputDialog, 'getItem', lambda *args, **kwargs: (args[3][0], True))
        window.restore_session()
        assert store.sessions(project)[0]['id'] == session
        assert window.session_id == session
    finally:
        qt.processEvents()
        window.close()
