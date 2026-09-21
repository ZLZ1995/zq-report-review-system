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
