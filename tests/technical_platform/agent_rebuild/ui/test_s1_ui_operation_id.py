"""S1 UI 侧验收：durable operation_id 贯通 + fallback 错误消息（先红后绿）。"""
import os
import time

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import pytest

pytest.importorskip('PySide6')
from PySide6.QtWidgets import QApplication

from asset_based_agent.technical_platform.app import PlatformWindow
from asset_based_agent.technical_platform.store import PlatformStore


class RepoGateway:
    """带真实 durable repo 的假网关：模拟 Kernel 已持久化/未持久化两种结局。"""

    def __init__(self, store, session_id, mode):
        from asset_based_agent.technical_platform.sessions.sqlite_repository import (
            SQLiteSessionRepo,
        )
        self.repo = SQLiteSessionRepo(store.path, store.owner)
        self.repo.create_session(session_id, project_id='p1',
                                 owner_id=store.owner, title='会话')
        self.session_id = session_id
        self.mode = mode
        self.last_operation_id = None

    def submit(self, text, *, on_event=None, file_ids=(), upload_ids=()):
        from asset_based_agent.technical_platform.agent_core.events import (
            AgentEvent,
        )
        operation = self.repo.begin_operation(
            self.session_id, 'main', user_text=text, request_id='r-ui')
        self.last_operation_id = operation.id
        if on_event is not None:
            on_event(AgentEvent(
                event_type='operation_accepted', session_id=self.session_id,
                lane_id='main', sequence=1, timestamp='now',
                operation_id=operation.id))
        if self.mode == 'completed':
            entry = self.repo.append_entry(
                self.session_id, 'main', 'assistant_message', {'text': '好的'},
                operation_id=operation.id)
            self.repo.complete_operation(
                operation.id, assistant_entry_id=entry.id, turn_id=None)
            return {'status': 'completed', 'reply': '好的', 'error_code': '',
                    'operation_id': operation.id}
        # failed_silent：Kernel 未写任何 terminal entry 的异常结局
        return {'status': 'failed', 'reply': '', 'error_code': 'model.timeout',
                'error_message': '', 'operation_id': operation.id}

    def stop(self):
        pass


def make_window(tmp_path, mode):
    app = QApplication.instance() or QApplication([])
    store = PlatformStore(tmp_path / 'state.sqlite', 'tester')
    project = store.create_project('p')
    session = store.create_session(project, 's')
    window = PlatformWindow(store)
    window.reload_projects(project)
    window.choose_session(next(
        window.sessions.item(i) for i in range(window.sessions.count())
        if window.sessions.item(i).data(0x0100) == session))
    gateway = RepoGateway(store, session, mode)
    window._make_agent_gateway = lambda: gateway
    return app, window, session, gateway


def pump(app, window, timeout=5):
    deadline = time.perf_counter() + timeout
    while window._agent_jobs and time.perf_counter() < deadline:
        app.processEvents()
        time.sleep(0.01)
    app.processEvents()


def test_status_controller_uses_durable_operation_id(tmp_path):
    app, window, session, gateway = make_window(tmp_path, 'completed')
    assert window._try_agent_submit('问') is True
    pump(app, window)
    operation_id = gateway.last_operation_id
    phase = window.status_controller.turn_phase(session, operation_id)
    assert phase is not None, '状态控制器必须按真实 durable operation_id 登记'
    assert phase.phase == 'completed'
    window.close()


def test_error_card_correlates_to_repo_operation(tmp_path):
    app, window, session, gateway = make_window(tmp_path, 'failed_silent')
    assert window._try_agent_submit('问') is True
    pump(app, window)
    operation_id = gateway.last_operation_id
    phase = window.status_controller.turn_phase(session, operation_id)
    assert phase is not None
    assert phase.phase == 'failed'
    assert phase.payload.get('error_code') == 'model.timeout'
    window.close()


def test_gateway_failure_without_kernel_error_entry_shows_fallback(tmp_path):
    app, window, session, gateway = make_window(tmp_path, 'failed_silent')
    assert window._try_agent_submit('问') is True
    pump(app, window)
    operation_id = gateway.last_operation_id
    errors = [e for e in gateway.repo.entries(session, 'main')
              if e.entry_type == 'error_message'
              and e.operation_id == operation_id]
    assert errors, 'Kernel 未写 terminal entry 时 UI 必须追加 fallback 错误'
    assert '本轮未完成' in errors[-1].payload.get('text', '')
    window.close()


def test_failed_turn_never_renders_blank_after_user_message(tmp_path):
    app, window, _session, _gateway = make_window(tmp_path, 'failed_silent')
    assert window._try_agent_submit('问') is True
    pump(app, window)
    transcript = window.transcript.toPlainText()
    assert '本轮未完成' in transcript, '失败轮次在用户消息后不得渲染空白'
    window.close()
