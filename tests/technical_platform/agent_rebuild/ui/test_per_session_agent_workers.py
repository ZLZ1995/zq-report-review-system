import os
import threading
import time
from types import SimpleNamespace

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import pytest

pytest.importorskip('PySide6')
from PySide6.QtWidgets import QApplication

from asset_based_agent.technical_platform.agent_switch import flags_store_for
from asset_based_agent.technical_platform.app import PlatformWindow
from asset_based_agent.technical_platform.store import PlatformStore


class SessionGateway:
    def __init__(self, reply):
        self.reply = reply
        self.release = threading.Event()

    def submit(self, text, *, on_event=None):
        self.release.wait(5)
        return {'status': 'completed', 'reply': self.reply, 'error_code': ''}

    def stop(self):
        self.release.set()


def pump(app, window, timeout=5):
    deadline = time.perf_counter() + timeout
    while window._agent_jobs and time.perf_counter() < deadline:
        app.processEvents()
        time.sleep(0.01)
    app.processEvents()


def test_agent_workers_are_isolated_by_session(tmp_path):
    app = QApplication.instance() or QApplication([])
    store = PlatformStore(tmp_path / 'state.sqlite', 'tester')
    project = store.create_project('p')
    first = store.create_session(project, 'first')
    second = store.create_session(project, 'second')
    window = PlatformWindow(store)
    window.reload_projects(project)
    window.choose_session(next(
        window.sessions.item(i) for i in range(window.sessions.count())
        if window.sessions.item(i).data(0x0100) == first))
    flags_store_for(store).set_enabled('chat', True)
    gateways = {first: SessionGateway('reply-first'),
                second: SessionGateway('reply-second')}
    window._make_agent_gateway = lambda: gateways[window.session_id]

    assert window._try_agent_submit('task-first') is True
    window.choose_session(next(
        window.sessions.item(i) for i in range(window.sessions.count())
        if window.sessions.item(i).data(0x0100) == second))
    assert window._try_agent_submit('task-second') is True
    assert set(window._agent_jobs) == {first, second}

    gateways[second].release.set()
    deadline = time.perf_counter() + 5
    while second in window._agent_jobs and time.perf_counter() < deadline:
        app.processEvents()
        time.sleep(0.01)
    window.choose_session(next(
        window.sessions.item(i) for i in range(window.sessions.count())
        if window.sessions.item(i).data(0x0100) == first))
    gateways[first].release.set()
    pump(app, window)
    assert 'reply-first' in window.transcript.toPlainText()
    window.choose_session(next(
        window.sessions.item(i) for i in range(window.sessions.count())
        if window.sessions.item(i).data(0x0100) == second))
    assert 'reply-second' in window.transcript.toPlainText()
    window.close()
