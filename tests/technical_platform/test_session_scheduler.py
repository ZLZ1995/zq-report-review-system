import os
import time
from threading import Event

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtCore import Qt
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QApplication, QListWidgetItem

from asset_based_agent.technical_platform.app import PlatformWindow, TaskWorker
from asset_based_agent.technical_platform.store import PlatformStore


class WaitingWorker(TaskWorker):
    def __init__(self, *args):
        super().__init__(*args)
        self.entered = Event()

    def run(self):
        self.entered.set()
        self.cancel.wait(10)


def test_two_background_chats_targeted_stop_and_close_wait(tmp_path):
    app = QApplication.instance() or QApplication([])
    store = PlatformStore(tmp_path / 'state.sqlite', 'alice')
    project = store.create_project('project')
    sessions = [store.create_session(project, str(i)) for i in range(3)]
    window = PlatformWindow(store)
    window.reload_projects(project)
    workers = []
    def choose(session):
        row = QListWidgetItem(session)
        row.setData(Qt.ItemDataRole.UserRole, session)
        window.choose_session(row)
    try:
        for session in sessions[:2]:
            choose(session)
            run = store.start_run(session, {'files': []})
            worker = window.register_task_worker(WaitingWorker(store, run, window))
            workers.append(worker)
            worker.start()
            assert worker.entered.wait(2)
            window.set_busy(True)
            assert window.worker is worker
            assert window.sidebar.isEnabled()
        choose(sessions[2])
        assert window.worker is None
        assert window.send.isEnabled() and not window.stop.isEnabled()
        choose(sessions[1])
        assert window.worker is workers[1]
        assert not window.send.isEnabled() and window.stop.isEnabled()
        window.cancel_run()
        assert workers[1].cancel.is_set() and not workers[0].cancel.is_set()
        choose(sessions[2])
        event = QCloseEvent()
        window.closeEvent(event)
        assert not event.isAccepted()
        assert workers[0].cancel.is_set()
        deadline = time.monotonic() + 5
        while window.task_manager.active() and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(.01)
        assert not window.task_manager.active()
        window.closeEvent(event)
        assert event.isAccepted()
    finally:
        for worker in workers:
            worker.cancel.set()
            try:
                worker.wait(2000)
            except RuntimeError:
                pass  # Qt may already have processed deleteLater after finished.
        app.processEvents()
        window.close()


def test_inflight_request_blocks_close_and_account_switch(tmp_path, monkeypatch):
    from asset_based_agent.report_review_app.services.resource_locks import (
        CLIENT_RESOURCES,
    )
    from asset_based_agent.technical_platform import app as ui
    qt = QApplication.instance() or QApplication([])
    assert qt is not None
    window = PlatformWindow(PlatformStore(tmp_path / 'state.sqlite', 'alice'))
    calls = []
    monkeypatch.setattr(ui, 'authenticate', lambda *args: calls.append(True))
    event = QCloseEvent()
    with CLIENT_RESOURCES.lease(('model',)):
        window.closeEvent(event)
        assert not event.isAccepted()
        assert window.connect_service() is False
        assert not calls
    window.closeEvent(event)
    assert event.isAccepted()
    window.close()


def test_two_real_preflights_complete_in_their_own_chats(tmp_path, monkeypatch):
    from threading import Lock

    from openpyxl import Workbook

    from asset_based_agent.technical_platform import execution
    from asset_based_agent.technical_platform.skills import PREFLIGHT, digest

    qt = QApplication.instance() or QApplication([])
    store = PlatformStore(tmp_path / 'state.sqlite', 'alice')
    project = store.create_project('project')
    sessions = [store.create_session(project) for _ in range(2)]
    files = []
    for name in ('first.xlsx', 'second.xlsx'):
        path = tmp_path / name
        book = Workbook()
        book.active['A1'] = name
        book.save(path)
        store.add_file(project, path, digest(path))
        files.append(next(item for item in store.files(project) if item['name'] == name))
    window = PlatformWindow(store)
    window.reload_projects(project)
    entered, release, lock = Event(), Event(), Lock()
    calls = []
    original = execution.preflight
    def synchronized(*args, **kwargs):
        with lock:
            calls.append(args[1])
            if len(calls) == 2:
                entered.set()
        assert release.wait(10)
        return original(*args, **kwargs)
    monkeypatch.setattr(execution, 'preflight', synchronized)
    runs = []
    try:
        for session, source in zip(sessions, files):
            row = QListWidgetItem(session)
            row.setData(Qt.ItemDataRole.UserRole, session)
            window.choose_session(row)
            window.execute_plan('检查本轮资料', PREFLIGHT, selected_files=[source])
            runs.append(window.run_id)
        assert entered.wait(3)
        assert len(window.task_manager.active()) == 2
        release.set()
        deadline = time.monotonic() + 15
        while window.task_manager.active() and time.monotonic() < deadline:
            qt.processEvents()
            time.sleep(.01)
        assert not window.task_manager.active()
        assert all(store.run(run)['state'] == 'succeeded' for run in runs)
        for index, session in enumerate(sessions):
            text = '\n'.join(item['text'] for item in store.messages(session))
            assert files[index]['name'] in text
            assert files[1 - index]['name'] not in text
    finally:
        release.set()
        window.task_manager.cancel_all()
        deadline = time.monotonic() + 5
        while window.task_manager.active() and time.monotonic() < deadline:
            qt.processEvents()
            time.sleep(.01)
        window.close()
