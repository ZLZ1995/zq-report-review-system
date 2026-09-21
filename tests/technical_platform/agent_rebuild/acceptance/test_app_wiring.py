# S15 接线子集：app.py 灰度接线（先红后绿）。
# 验证：flags 全关走旧路径；chat 开且无客户端时提示并回退；开启后 submit
# 路由进 AgentGateway（用户/助手消息双写旧表供 UI 显示）；灰度菜单持久化；
# cancel_run 能停止新路径轮次。
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


def make_window(tmp_path):
    app = QApplication.instance() or QApplication([])
    store = PlatformStore(tmp_path / 'state.sqlite', 'tester')
    project = store.create_project('接线项目')
    session = store.create_session(project, '接线会话')
    window = PlatformWindow(store)
    window.reload_projects(project)
    assert window.session_id == session
    return app, store, window


def drain(app, window, timeout=10.0):
    deadline = time.perf_counter() + timeout
    while window._agent_worker is not None and time.perf_counter() < deadline:
        app.processEvents()
        time.sleep(0.01)
    app.processEvents()


class FakeGateway:
    def __init__(self):
        self.calls = []
        self.stopped = False
        self.new_path_available = True

    def submit(self, text, *, on_event=None):
        self.calls.append(text)
        if on_event is not None:
            on_event(SimpleNamespace(event_type='message_delta',
                                     payload={'text': '新'}))
        return {'status': 'completed', 'reply': '新路径回复', 'error_code': ''}

    def stop(self):
        self.stopped = True


class BlockingGateway(FakeGateway):
    def __init__(self):
        super().__init__()
        self.release = threading.Event()

    def submit(self, text, *, on_event=None):
        self.calls.append(text)
        self.release.wait(10)
        return {'status': 'aborted', 'reply': '', 'error_code': 'aborted'}

    def stop(self):
        self.stopped = True
        self.release.set()


class FailingGateway(FakeGateway):
    def submit(self, text, *, on_event=None):
        self.calls.append(text)
        return {'status': 'failed', 'reply': '',
                'error_code': 'server.capability_missing',
                'error_message': '服务端尚未部署新 Agent 流式接口，请先升级服务端'}


class SlowStreamingGateway(FakeGateway):
    def submit(self, text, *, on_event=None):
        self.calls.append(text)
        for part in ('第一段', '第二段'):
            if on_event is not None:
                on_event(SimpleNamespace(event_type='message_delta',
                                         payload={'text': part}))
            time.sleep(0.11)
        return {'status': 'completed', 'reply': '第一段第二段', 'error_code': ''}


# ---------------------------------------------------------------- 回退

def test_flags_off_still_uses_new_agent_in_single_path_build(tmp_path):
    _app, _store, window = make_window(tmp_path)
    assert window._try_agent_submit('你好') is True
    assert window._agent_worker is None
    window.close()


def test_without_client_blocks_new_agent_without_legacy_fallback(tmp_path):
    _app, store, window = make_window(tmp_path)
    flags_store_for(store).set_enabled('chat', True)
    assert window._try_agent_submit('你好') is True
    assert '连接服务端' in window.status.text()
    assert window._agent_worker is None
    window.close()


# ---------------------------------------------------------------- 路由

def test_submit_routes_to_gateway_when_flag_on(tmp_path):
    app, store, window = make_window(tmp_path)
    flags_store_for(store).set_enabled('chat', True)
    gateway = FakeGateway()
    window._make_agent_gateway = lambda: gateway
    window.composer.setPlainText('你好')
    window.submit()
    assert window._agent_worker is not None
    assert not window.composer.toPlainText()
    drain(app, window)  # Worker 线程异步执行，先等本轮结束
    assert gateway.calls == ['你好']
    transcript = window.transcript.toPlainText()
    assert '你好' in transcript  # 灰期双写：用户消息
    assert '新路径回复' in transcript  # 灰期双写：助手回复
    assert window._agent_worker is None
    window.close()


def test_single_path_failure_keeps_user_and_records_actionable_assistant(tmp_path):
    app, _store, window = make_window(tmp_path)
    gateway = FailingGateway()
    window._make_agent_gateway = lambda: gateway
    window.composer.setPlainText('根据资料生成评估明细表')
    window.submit()
    drain(app, window)
    transcript = window.transcript.toPlainText()
    assert '根据资料生成评估明细表' in transcript
    assert '服务端尚未部署新 Agent 流式接口' in transcript
    assert 'model.protocol_error' not in transcript
    window.close()


def test_streaming_reply_is_visible_in_conversation_panel_before_completion(tmp_path):
    app, _store, window = make_window(tmp_path)
    gateway = SlowStreamingGateway()
    window._make_agent_gateway = lambda: gateway
    window.composer.setPlainText('流式测试')
    window.submit()
    deadline = time.perf_counter() + 0.5
    while time.perf_counter() < deadline and '第一段' not in window.transcript.toPlainText():
        app.processEvents()
        time.sleep(0.01)
    assert '流式测试' in window.transcript.toPlainText()
    assert '第一段' in window.transcript.toPlainText()
    drain(app, window)
    assert '第一段第二段' in window.transcript.toPlainText()
    window.close()


def test_single_path_routes_even_when_legacy_flag_state_is_off(tmp_path):
    app, _store, window = make_window(tmp_path)
    gateway = FakeGateway()
    gateway.new_path_available = False
    window._make_agent_gateway = lambda: gateway
    assert window._try_agent_submit('你好') is True
    drain(app, window)
    assert gateway.calls == ['你好']
    window.close()


# ---------------------------------------------------------------- 灰度菜单

def test_grayscale_menu_persists_flags(tmp_path):
    _app, store, window = make_window(tmp_path)
    actions = window.grayscale_button.menu().actions()
    assert len(actions) == 10
    assert all(action.isCheckable() for action in actions)
    assert not any(action.isChecked() for action in actions)
    assert '0/10' in window.grayscale_button.text()
    actions[0].trigger()  # chat → 新路径
    assert flags_store_for(store).enabled('chat') is True
    assert '1/10' in window.grayscale_button.text()
    actions2 = window.grayscale_button.menu().actions()
    assert actions2[0].isChecked()
    actions2[0].trigger()  # 退回旧路径
    assert flags_store_for(store).enabled('chat') is False
    assert '0/10' in window.grayscale_button.text()
    window.close()
    reopened = PlatformWindow(store)
    assert reopened.grayscale_button.menu().actions()[0].isChecked() is False
    reopened.close()


# ---------------------------------------------------------------- 停止

def test_cancel_run_stops_agent_worker(tmp_path):
    app, store, window = make_window(tmp_path)
    flags_store_for(store).set_enabled('chat', True)
    gateway = BlockingGateway()
    window._make_agent_gateway = lambda: gateway
    window.composer.setPlainText('长跑任务')
    window.submit()
    assert window._agent_worker is not None
    window.cancel_run()
    assert gateway.stopped is True
    drain(app, window)
    assert window._agent_worker is None
    window.close()


# ---------------------------------------------------------------- ProjectCatalog 未激活

def make_catalog_window(tmp_path):
    from asset_based_agent.technical_platform.project_catalog import ProjectCatalog

    app = QApplication.instance() or QApplication([])
    catalog = ProjectCatalog(tmp_path / 'index.sqlite', 'tester')
    assert catalog.active is None  # 未创建/打开项目：.path 访问会 ValueError
    window = PlatformWindow(catalog)
    return app, catalog, window


def test_window_constructs_with_inactive_catalog(tmp_path):
    # 回归：未激活 ProjectCatalog 启动时灰度菜单不得打崩启动（内存开关回退）
    _app, _catalog, window = make_catalog_window(tmp_path)
    assert '0/10' in window.grayscale_button.text()
    assert window._try_agent_submit('你好') is True
    actions = window.grayscale_button.menu().actions()
    actions[0].trigger()  # 内存期可勾选，不落盘
    assert '1/10' in window.grayscale_button.text()
    assert not (tmp_path / 'agent_feature_flags.json').exists()
    window.close()


def test_flags_rebind_to_project_file_when_catalog_activates(tmp_path, monkeypatch):
    _app, catalog, window = make_catalog_window(tmp_path)
    window.grayscale_button.menu().actions()[0].trigger()  # 内存期勾选 chat
    directory = tmp_path / 'proj'
    directory.mkdir()
    monkeypatch.setenv('SystemDrive', 'Z:')
    catalog.create_project('接线项目', directory)
    flags = window._feature_flags()
    assert flags.path is not None  # 已重新绑定到项目库同目录文件
    assert flags.enabled('chat') is True  # 内存期勾选被迁移
    from asset_based_agent.technical_platform.flags import FeatureFlagStore
    assert FeatureFlagStore(flags.path).enabled('chat') is True  # 已落盘
    window.close()


# ================================================================ S16 时间线 UI

def test_reply_displayed_once_and_no_fixed_status_bar(tmp_path):
    """T1：回复只出现一次；输入框上方不存在可见通用状态栏。"""
    app, store, window = make_window(tmp_path)
    flags_store_for(store).set_enabled('chat', True)
    gateway = FakeGateway()
    window._make_agent_gateway = lambda: gateway
    window.composer.setPlainText('你好')
    window.submit()
    drain(app, window)
    transcript = window.transcript.toPlainText()
    assert transcript.count('新路径回复') == 1
    assert not window.status.isVisible()  # 固定状态栏已拆除
    assert '新路径回复' not in window.status.text()  # 适配器不得显示完整回复
    window.close()


def test_live_status_in_timeline_then_replaced(tmp_path):
    """T2：轮次状态进入对话时间线（用户消息之后），完成后被终态替换。"""
    app, store, window = make_window(tmp_path)
    flags_store_for(store).set_enabled('chat', True)
    gateway = BlockingGateway()
    window._make_agent_gateway = lambda: gateway
    window.composer.setPlainText('长跑任务')
    window.submit()
    deadline = time.perf_counter() + 5
    while '正在生成' not in window.transcript.toPlainText() \
            and time.perf_counter() < deadline:
        app.processEvents()
        time.sleep(0.02)
    running_html = window.transcript.toPlainText()
    assert '正在生成' in running_html
    assert running_html.index('长跑任务') < running_html.index('正在生成')  # 状态在本轮消息之后
    gateway.stop()
    drain(app, window)
    final_text = window.transcript.toPlainText()
    assert '正在生成' not in final_text  # 临时状态已消失
    assert '本轮未完成：aborted' in final_text  # 终态原位替换
    window.close()


def test_empty_session_hint_lives_in_transcript(tmp_path):
    """T3：空会话提示只出现在 transcript 空状态，首条消息后消失。"""
    app, store, window = make_window(tmp_path)
    assert '添加本轮资料' in window.transcript.toPlainText()
    assert '添加本轮资料' not in window.status.text()  # 不再占用状态适配器
    flags_store_for(store).set_enabled('chat', True)
    gateway = FakeGateway()
    window._make_agent_gateway = lambda: gateway
    window.composer.setPlainText('你好')
    window.submit()
    drain(app, window)
    assert '添加本轮资料' not in window.transcript.toPlainText()
    window.close()


def test_artifacts_stay_with_owning_message(tmp_path):
    """T4：历史成果锚定产生它的回复；新聊天不带出旧成果；无归属旧 run 进独立区域。"""
    import json as _json

    _app, store, window = make_window(tmp_path)
    session = window.session_id
    user1 = store.append(session, 'user', '审核这份报告')
    run = store.start_run(session, {'selected_files': [], 'permissions': {}})
    store.transition(run, 'running', 's')
    store.transition(run, 'validating', 'c')
    store.transition(run, 'succeeded', 'd')
    with store.connect() as db:
        db.execute('UPDATE runs SET result=? WHERE id=?',
                   (_json.dumps({'kind': 'review', 'issues': [{'rule': 'x'}]}), run))
    store.append_and_link(session, 'assistant', '审核完成，返回 1 项问题；原文件未变化。',
                          run, source_message_id=user1)
    # 无归属旧 run（迁移前数据形态）
    with store.connect() as db:
        db.execute("INSERT INTO runs VALUES('legacy-run',?,?,?,?,?)",
                   (session, 'succeeded', '{}',
                    _json.dumps({'kind': 'review', 'issues': []}),
                    '2020-01-01T00:00:00+00:00'))
    store.append(session, 'user', '你好')
    store.append(session, 'assistant', '你好，请问需要核对哪些资料？')
    window.render_messages()
    html = window.transcript.toHtml()
    artifact_pos = html.find('zq-export:')
    assert artifact_pos != -1
    second_turn_pos = html.find('你好，请问需要核对哪些资料？')
    assert artifact_pos < second_turn_pos  # 成果仍在第一轮回复之下
    zone_pos = html.find('历史成果（旧版本）')
    assert zone_pos != -1
    assert zone_pos > second_turn_pos  # 无归属旧成果在独立区域，不挂最新回复
    # 重新构造窗口（模拟重启）顺序不变
    project_id = window.project_id
    window.close()
    reopened = PlatformWindow(store)
    reopened.reload_projects(project_id)
    reopened.render_messages()
    html2 = reopened.transcript.toHtml()
    assert html2.find('zq-export:') < html2.find('你好，请问需要核对哪些资料？')
    reopened.close()


def test_cancel_produces_single_event_without_duplicate(tmp_path):
    """T8：取消只产生一条时间线内容，不与固定状态文字重复。"""
    app, store, window = make_window(tmp_path)
    flags_store_for(store).set_enabled('chat', True)
    gateway = BlockingGateway()
    window._make_agent_gateway = lambda: gateway
    window.composer.setPlainText('长跑任务')
    window.submit()
    window.cancel_run()
    drain(app, window)
    transcript = window.transcript.toPlainText()
    assert transcript.count('本轮未完成') == 1
    assert '本轮未完成' not in window.status.text()
    window.close()
