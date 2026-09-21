import os
from threading import Event
from types import SimpleNamespace

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtWidgets import QApplication

from asset_based_agent.technical_platform.app import PlatformWindow
from asset_based_agent.technical_platform.session_service import SessionService
from asset_based_agent.technical_platform.store import PlatformStore
from asset_based_agent.technical_platform.task_manager import TaskBinding


def test_closed_window_stops_status_timer(tmp_path):
    qt = QApplication.instance() or QApplication([])
    window = PlatformWindow(PlatformStore(tmp_path / 'state.sqlite', 'alice'))
    assert window.session_badge_timer.isActive()
    window.close()
    qt.processEvents()
    assert not window.session_badge_timer.isActive()


def test_badge_timer_ready_before_restoring_history(tmp_path, monkeypatch):
    qt = QApplication.instance() or QApplication([])
    original = PlatformWindow.reload_projects
    def restore(window, selected=None):
        assert hasattr(window, 'session_badge_timer')
        return original(window, selected)
    monkeypatch.setattr(PlatformWindow, 'reload_projects', restore)
    window = PlatformWindow(PlatformStore(tmp_path / 'state.sqlite', 'alice'))
    qt.processEvents()
    window.close()


def test_background_unread_and_running_badges_do_not_switch_chat(tmp_path):
    qt = QApplication.instance() or QApplication([])
    store = PlatformStore(tmp_path / 'state.sqlite', 'alice')
    project = store.create_project('p')
    first = store.create_session(project, 'first')
    second = store.create_session(project, 'second')
    window = PlatformWindow(store)
    window.reload_projects(project)
    window.reload_sessions(first)
    worker = SimpleNamespace(cancel=Event(), isRunning=lambda: True)
    binding = TaskBinding('alice', project, second, 'understanding:test')
    window.task_manager.register(binding, worker)
    try:
        store.append(second, 'assistant', 'background result')
        window.refresh_session_badges()
        labels = [window.sessions.item(i).text() for i in range(window.sessions.count())]
        assert any('second' in text and '未读 1' in text and '运行中' in text for text in labels)
        assert window.session_id == first
        window.reload_sessions(second)
        window.refresh_session_badges()
        assert not any('未读' in window.sessions.item(i).text() for i in range(window.sessions.count()))
        assert next(r for r in SessionService(store).list(project) if r['id'] == second)['unread_count'] == 0
    finally:
        worker.isRunning = lambda: False
        window.task_manager.finish(binding, worker)
        qt.processEvents()
        window.close()
