"""S6-01 每会话独立 live render state（先红后绿）。

验收（总任务书 S6-01）：
- 当前会话切换不影响后台任务；
- 后台会话完成不停止当前会话 timer；
- 每 session 的 live text 独立。
"""
import os

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import pytest

pytest.importorskip('PySide6')
from PySide6.QtWidgets import QApplication

USER_ROLE = 0x0100


def make_window(tmp_path):
    from asset_based_agent.technical_platform.app import PlatformWindow
    from asset_based_agent.technical_platform.store import PlatformStore
    store = PlatformStore(tmp_path / 'state.sqlite', 'tester')
    project = store.create_project('p')
    first = store.create_session(project, 'first')
    second = store.create_session(project, 'second')
    window = PlatformWindow(store)
    window.reload_projects(project)
    window.choose_session(item_for(window, first))
    return window, first, second


def item_for(window, session_id):
    return next(
        window.sessions.item(i) for i in range(window.sessions.count())
        if window.sessions.item(i).data(USER_ROLE) == session_id)


def add_job(window, session_id):
    window._agent_jobs[session_id] = {
        'worker': None, 'gateway': None, 'operation_id': None,
        'user_text': 'task', 'live_text': '',
    }


def test_background_done_does_not_stop_current_timer(tmp_path):
    """A 持续流式、B 提前完成：B 完成后 A 的 live timer 必须继续运转。"""
    QApplication.instance() or QApplication([])
    window, first, second = make_window(tmp_path)
    add_job(window, first)
    add_job(window, second)
    window._on_agent_delta_for(first, 'a-1')
    assert window._live_render_timer.isActive()
    window._on_agent_delta_for(second, 'b-1')
    window._on_agent_done_for(second, {'status': 'completed', 'reply': 'b-done'})
    # 后台会话完成不得停止当前会话的 live 刷新
    assert window._live_render_timer.isActive()
    window._flush_live_agent_render()
    assert 'a-1' in window.transcript.toPlainText()
    window._agent_jobs.clear()
    window.close()


def test_live_text_isolated_per_session(tmp_path):
    """每个 session 的 live text 独立：只渲染当前会话的增量。"""
    QApplication.instance() or QApplication([])
    window, first, second = make_window(tmp_path)
    add_job(window, first)
    add_job(window, second)
    window._on_agent_delta_for(first, 'alpha-live')
    window._on_agent_delta_for(second, 'beta-live')
    window._flush_live_agent_render()
    text = window.transcript.toPlainText()
    assert 'alpha-live' in text
    assert 'beta-live' not in text
    window.choose_session(item_for(window, second))
    text = window.transcript.toPlainText()
    assert 'beta-live' in text
    assert 'alpha-live' not in text
    window._agent_jobs.clear()
    window.close()


def test_switch_away_and_back_keeps_live_state(tmp_path):
    """切走再切回：后台期间累积的 live text 不丢失、继续刷新。"""
    QApplication.instance() or QApplication([])
    window, first, second = make_window(tmp_path)
    add_job(window, first)
    add_job(window, second)
    window._on_agent_delta_for(first, 'a-1')
    window.choose_session(item_for(window, second))
    # 用户在 second 上，first 后台继续流式
    window._on_agent_delta_for(first, 'a-2')
    window._on_agent_delta_for(second, 'b-1')
    window.choose_session(item_for(window, first))
    text = window.transcript.toPlainText()
    assert 'a-1' in text and 'a-2' in text
    # 回到 first 后继续 delta，timer 必须能再次启动
    window._on_agent_delta_for(first, 'a-3')
    assert window._live_render_timer.isActive()
    window._flush_live_agent_render()
    assert 'a-3' in window.transcript.toPlainText()
    window._agent_jobs.clear()
    window.close()


def test_done_for_current_stops_timer_only_when_nothing_pending(tmp_path):
    """当前会话完成且无其他待刷新会话时，timer 才停止。"""
    QApplication.instance() or QApplication([])
    window, first, _second = make_window(tmp_path)
    add_job(window, first)
    window._on_agent_delta_for(first, 'a-1')
    assert window._live_render_timer.isActive()
    window._on_agent_done_for(first, {'status': 'completed', 'reply': 'a-done'})
    assert not window._live_render_timer.isActive()
    assert 'a-done' in window.transcript.toPlainText()
    window._agent_jobs.clear()
    window.close()
