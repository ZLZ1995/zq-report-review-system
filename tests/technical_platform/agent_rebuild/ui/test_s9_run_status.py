"""S9 运行状态与任务反馈（先红后绿）。

验收（任务书 S9）：实时运行状态卡、elapsed time、last activity、
stopping / waiting_user / failed / cancelled / completed 状态、Stepper、
执行/停止按钮状态重构（disable 必须有原因）。
铁律：状态来自真实任务状态与真实 operation_id；无真实百分比时只显示
步骤进度；unknown 不得显示为"失败"。
"""
from __future__ import annotations

import os
import threading
import time

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import pytest

pytest.importorskip('PySide6')
from PySide6.QtWidgets import QApplication

from asset_based_agent.technical_platform.conversation_status import (
    ACTIVE_PHASES,
    ConversationStatusController,
)
from asset_based_agent.technical_platform.run_status import (
    RUN_STATE_LABELS,
    RUN_STEPS,
    RunStatusView,
    derive_run_state,
    derive_step,
    format_duration,
    format_last_activity,
    status_card_html,
    terminal_line_html,
)

# ------------------------------------------------------------ 状态映射

def test_all_states_have_labels_and_unknown_is_never_failed():
    for state in ('queued', 'running', 'waiting_user', 'stopping',
                  'completed', 'failed', 'cancelled', 'unknown'):
        assert state in RUN_STATE_LABELS, f'缺少状态文案: {state}'
        assert RUN_STATE_LABELS[state].strip()
    # 铁律：未知状态不得显示成"失败"
    assert '失败' not in RUN_STATE_LABELS['unknown']
    assert '待核对' in RUN_STATE_LABELS['unknown']


def test_derive_run_state_mapping():
    assert derive_run_state('running') == 'running'
    assert derive_run_state('queued') == 'queued'
    # stopping：真实 stop 请求 + 仍在运行
    assert derive_run_state('running', stop_requested=True) == 'stopping'
    # waiting_user：durable operation 的等待态
    assert derive_run_state(
        'running', operation_status='waiting_approval') == 'waiting_user'
    assert derive_run_state(
        'running', operation_status='waiting_input') == 'waiting_user'
    # unknown：不得映射成 failed
    assert derive_run_state('running', operation_status='unknown') == 'unknown'
    # 终态原样通过，stop 请求不得把终态拉回 stopping
    assert derive_run_state('completed', stop_requested=True) == 'completed'
    assert derive_run_state('failed') == 'failed'
    assert derive_run_state('cancelled') == 'cancelled'


# ------------------------------------------------------------ 计时

def test_format_duration():
    assert format_duration(0) == '00:00'
    assert format_duration(59) == '00:59'
    assert format_duration(61) == '01:01'
    assert format_duration(3661) == '1:01:01'


def test_format_last_activity():
    assert format_last_activity(None) == '暂无活动记录'
    assert format_last_activity(1) == '刚刚'
    assert format_last_activity(5) == '5 秒前'
    assert format_last_activity(125) == '2 分钟前'


# ------------------------------------------------------------ Stepper

def test_stepper_derives_from_real_progress_without_fake_percent():
    assert len(RUN_STEPS) == 4
    assert derive_step(accepted=False, has_output=False,
                       tools_running=0) == 0
    assert derive_step(accepted=True, has_output=False,
                       tools_running=0) == 1
    assert derive_step(accepted=True, has_output=True,
                       tools_running=0) == 1
    assert derive_step(accepted=True, has_output=True,
                       tools_running=2) == 2
    assert derive_step(accepted=True, has_output=True, tools_running=0,
                       finishing=True) == 3
    # 无真实百分比：视图结构不携带 percent 字段
    view = RunStatusView(state='running', operation_id='op-1',
                         elapsed_seconds=3, last_activity_seconds=1,
                         step_index=1, text='生成中')
    assert not hasattr(view, 'percent')


# ------------------------------------------------------------ 卡片 HTML

def _view(**overrides):
    base = {'state': 'running', 'operation_id': 'op-abcdef123456',
            'elapsed_seconds': 75, 'last_activity_seconds': 5,
            'step_index': 1, 'text': '正在生成…'}
    base.update(overrides)
    return RunStatusView(**base)


def test_status_card_html_shows_identity_elapsed_activity_stepper():
    rendered = status_card_html(_view())
    assert '运行中' in rendered
    assert 'op-abcdef' in rendered, '卡片必须携带真实 operation id'
    assert '01:15' in rendered, '卡片必须显示 elapsed time'
    assert '5 秒前' in rendered, '卡片必须显示 last activity'
    for step in RUN_STEPS:
        assert step in rendered, 'stepper 必须列出全部步骤'
    assert '正在生成…' in rendered


def test_status_card_html_waiting_and_stopping():
    assert '等待你的确认' in status_card_html(_view(state='waiting_user'))
    assert '正在停止' in status_card_html(_view(state='stopping'))


def test_terminal_line_html_states():
    done = terminal_line_html(_view(state='completed', elapsed_seconds=65))
    assert '已完成' in done and '01:05' in done and 'op-abcdef' in done
    failed = terminal_line_html(_view(state='failed'))
    assert '失败' in failed
    cancelled = terminal_line_html(_view(state='cancelled'))
    assert '已取消' in cancelled
    unknown = terminal_line_html(_view(state='unknown'))
    assert '待核对' in unknown and '失败' not in unknown


# ------------------------------------------------------------ 控制器扩展

def test_controller_stopping_and_waiting_user_are_active_phases():
    controller = ConversationStatusController()
    controller.set_turn_phase('s1', 'op-1', '生成中')
    controller.waiting_user_turn('s1', 'op-1', '等待确认')
    assert controller.turn_phase('s1', 'op-1').phase == 'waiting_user'
    assert 'waiting_user' in ACTIVE_PHASES
    controller.stopping_turn('s1', 'op-1', '正在停止')
    assert controller.turn_phase('s1', 'op-1').phase == 'stopping'
    assert 'stopping' in ACTIVE_PHASES


def test_controller_records_started_at_and_last_activity():
    controller = ConversationStatusController()
    controller.set_turn_phase('s1', 'op-1', '生成中')
    first = controller.turn_phase('s1', 'op-1')
    assert first.started_at > 0
    assert first.last_activity_at >= first.started_at
    time.sleep(0.02)
    controller.set_turn_phase('s1', 'op-1', '继续生成')
    second = controller.turn_phase('s1', 'op-1')
    assert second.started_at == first.started_at, 'started_at 只在首轮记录'
    assert second.last_activity_at > first.last_activity_at
    controller.complete_turn('s1', 'op-1', '完成')
    done = controller.turn_phase('s1', 'op-1')
    assert done.last_activity_at >= second.last_activity_at


# ------------------------------------------------------------ Qt 集成

class S9Gateway:
    """带真实 durable repo 的阻塞网关：accepted → 保持运行 → stop 后 aborted。"""

    def __init__(self, store, session_id):
        from asset_based_agent.technical_platform.sessions.sqlite_repository import (
            SQLiteSessionRepo,
        )
        self.repo = SQLiteSessionRepo(store.path, store.owner)
        self.repo.create_session(session_id, project_id='p1',
                                 owner_id=store.owner, title='会话')
        self.session_id = session_id
        self.release = threading.Event()
        self.operation_id = None

    def submit(self, text, *, on_event=None, file_ids=(), upload_ids=()):
        from asset_based_agent.technical_platform.agent_core.events import (
            AgentEvent,
        )
        operation = self.repo.begin_operation(
            self.session_id, 'main', user_text=text, request_id='r-s9')
        self.operation_id = operation.id
        if on_event is not None:
            on_event(AgentEvent(
                event_type='operation_accepted',
                session_id=self.session_id, lane_id='main', sequence=1,
                timestamp='now', operation_id=operation.id))
        self.release.wait(10)
        if on_event is not None:
            self.repo.abort_operation(operation.id, turn_id=None)
        return {'status': 'aborted', 'reply': '', 'error_code': 'aborted',
                'operation_id': operation.id}

    def stop(self):
        # 真实语义：stop 只是请求，收束由 worker 随后完成；
        # 测试中由用例显式 release，模拟"停止中"窗口期。
        self.stopped = True


def _make_window(tmp_path):
    from asset_based_agent.technical_platform.agent_switch import (
        flags_store_for,
    )
    from asset_based_agent.technical_platform.app import PlatformWindow
    from asset_based_agent.technical_platform.store import PlatformStore
    app = QApplication.instance() or QApplication([])
    store = PlatformStore(tmp_path / 'state.sqlite', 'tester')
    project = store.create_project('s9 项目')
    session = store.create_session(project, 's9 会话')
    window = PlatformWindow(store)
    window.reload_projects(project)
    assert window.session_id == session
    flags_store_for(store).set_enabled('chat', True)
    return app, store, window, session


def _pump_until(app, predicate, timeout=5.0):
    deadline = time.perf_counter() + timeout
    while not predicate() and time.perf_counter() < deadline:
        app.processEvents()
        time.sleep(0.02)
    app.processEvents()


def test_running_card_cancel_and_terminal_replacement(tmp_path):
    app, store, window, session = _make_window(tmp_path)
    gateway = S9Gateway(store, session)
    window._make_agent_gateway = lambda: gateway
    window.composer.setPlainText('长跑任务')
    window.submit()

    _pump_until(app, lambda: gateway.operation_id is not None
                and '运行中' in window.transcript.toPlainText())
    text = window.transcript.toPlainText()
    assert '运行中' in text, '实时状态卡必须显示运行中'
    assert '用时' in text, '状态卡必须显示 elapsed time'
    assert '模型生成' in text, '状态卡必须显示 stepper'
    assert gateway.operation_id[:9] in text.replace('-', ''), \
        '状态卡必须携带真实 operation id'

    # 按钮状态重构：运行中 send 禁用且带原因，stop 可用且带说明
    assert not window.send.isEnabled()
    assert window.send.toolTip(), '禁用按钮必须给出原因'
    assert window.stop.isEnabled() and window.stop.toolTip()

    window.cancel_run()
    _pump_until(app, lambda: '正在停止' in window.transcript.toPlainText())
    assert '正在停止' in window.transcript.toPlainText(), \
        '停止后必须进入 stopping 状态'

    gateway.release.set()  # 停止请求生效，worker 收束
    _pump_until(app, lambda: not window._agent_jobs)
    final = window.transcript.toPlainText()
    assert '正在生成' not in final and '正在停止' not in final, \
        '临时状态卡必须被终态替换'
    assert '已取消' in final, '终态必须显示 cancelled'
    assert '用时' in final
    # 终态后按钮复位：send 可用、stop 禁用且带原因
    assert window.send.isEnabled()
    assert not window.stop.isEnabled() and window.stop.toolTip()
    window.close()


def test_completed_terminal_line_uses_real_elapsed(tmp_path):
    app, store, window, session = _make_window(tmp_path)

    class ImmediateGateway(S9Gateway):
        def submit(self, text, *, on_event=None, file_ids=(), upload_ids=()):
            from asset_based_agent.technical_platform.agent_core.events import (
                AgentEvent,
            )
            operation = self.repo.begin_operation(
                self.session_id, 'main', user_text=text, request_id='r-s9b')
            self.operation_id = operation.id
            if on_event is not None:
                on_event(AgentEvent(
                    event_type='operation_accepted',
                    session_id=self.session_id, lane_id='main', sequence=1,
                    timestamp='now', operation_id=operation.id))
            entry = self.repo.append_entry(
                self.session_id, 'main', 'assistant_message', {'text': '好的'},
                operation_id=operation.id)
            self.repo.complete_operation(
                operation.id, assistant_entry_id=entry.id, turn_id=None)
            return {'status': 'completed', 'reply': '好的', 'error_code': '',
                    'operation_id': operation.id}

    fast = ImmediateGateway(store, session)
    window._make_agent_gateway = lambda: fast
    window.composer.setPlainText('快速任务')
    window.submit()
    _pump_until(app, lambda: not window._agent_jobs)
    final = window.transcript.toPlainText()
    assert '已完成' in final, '终态必须显示 completed'
    assert '用时 00:0' in final, '终态必须显示真实用时'
    window.close()
