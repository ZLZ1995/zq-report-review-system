"""Project-first local preview. Remote authentication is integrated separately."""

from __future__ import annotations

import argparse
import html
import json
import os
import shutil
import sqlite3
import sys
import threading
import time
from pathlib import Path
from typing import ClassVar

from PySide6.QtCore import (
    QEvent,
    QSignalBlocker,
    QStandardPaths,
    Qt,
    QThread,
    QTimer,
    QUrl,
    Signal,
)
from PySide6.QtGui import QDesktopServices, QFont, QFontDatabase
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTabWidget,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from .agent_controller import ClarificationContextLimit
from .artifact_panel import (
    artifact_row_text,
    collect_artifacts,
    task_detail_text,
    task_row_text,
)
from .composer import ChatComposer
from .execution import execute_task
from .file_panel import build_file_rows, file_detail_text, filter_rows, row_label
from .project_catalog import ProjectCatalog
from .release_info import CLIENT_VERSION, inspect_server, local_release, release_details
from .skills import BUILTINS, GENERATORS, REVIEW, SkillRegistry, digest
from .store import PlatformStore
from .task_events import CompletionEventRelay, TaskDestination, TaskEventRelay
from .task_manager import TaskBinding, TaskManager
from .task_spec import build_task_spec

SERVER_URL = "https://zq-report-review.zeabur.app/api/v1"


def installation_root() -> Path:
    if os.environ.get('ZQ_INSTALLATION_ROOT'):
        return Path(os.environ['ZQ_INSTALLATION_ROOT']).resolve()
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).parent.resolve()
    # Developer/test runs are not an installed product and must not dirty the repo.
    return (Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppLocalDataLocation))
            / 'ZQPlatform-development').resolve()


def platform_settings_root() -> Path:
    # 冒烟/验收可用 ZQ_SETTINGS_ROOT 把设置引出冻结目录；默认行为不变（便携安装不落 C 盘）。
    override = os.environ.get('ZQ_SETTINGS_ROOT')
    base = Path(override).resolve() if override else installation_root()
    root = base / 'data' / 'settings'
    root.mkdir(parents=True, exist_ok=True)
    legacy = (Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppLocalDataLocation))
              / 'ZQPlatform')
    for name in ('client-instance.json', 'storage-locations.sqlite', 'project-locations.sqlite'):
        source, target = legacy / name, root / name
        if not target.exists() and source.is_file():
            shutil.copy2(source, target)
    return root


def authenticate(parent=None):
    """Login before workspace construction; users never configure an API endpoint."""
    from ..report_review_app.services.remote_auth_service import (
        RemoteSessionClient,
        WindowsCredentialStore,
        load_or_create_client_instance_id,
    )
    from .login import PlatformLogin
    from .session import PlatformSession

    state_dir = platform_settings_root()
    client = RemoteSessionClient(
        SERVER_URL,
        client_instance_id=load_or_create_client_instance_id(state_dir / "client-instance.json"),
        credential_store=WindowsCredentialStore("ZQPlatform-Production"),
    )
    dialog = PlatformLogin(PlatformSession(client), parent)
    if dialog.exec() != QDialog.DialogCode.Accepted:
        client.http_client.close()
        return None
    if dialog.result_payload.get("offline"):
        client.http_client.close()
        return None, dialog.result_payload
    return client, dialog.result_payload


def configure_fonts():
    """Offscreen Qt on Windows does not automatically enumerate installed fonts."""
    path = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / "msyh.ttc"
    if path.is_file():
        font_id = QFontDatabase.addApplicationFont(str(path))
        families = QFontDatabase.applicationFontFamilies(font_id)
        if families:
            QApplication.setFont(QFont(families[0], 10))


class TaskWorker(QThread):
    progress = Signal(str)
    output = Signal(object)
    completed = Signal(object)
    failed = Signal(str)

    def __init__(self, store, run_id, parent=None, provider=None, client=None):
        super().__init__(parent)
        self.store = store.active if isinstance(store, ProjectCatalog) else store
        if self.store is None:
            raise ValueError('执行任务前必须选择项目')
        self.run_id = run_id
        self.cancel = threading.Event()
        self.provider = provider
        self.client = client

    def run(self):
        try:
            result = execute_task(
                self.store,
                self.run_id,
                self.cancel,
                self.progress.emit,
                provider=self.provider,
                output=self.output.emit,
                client=self.client,
            )
            self.completed.emit(result)
        except Exception as exc:
            # The harness owns state transitions; a rejected duplicate owns no run.
            self.failed.emit(str(exc))


class PlatformWindow(QMainWindow):
    # S15 接线子集：Worker 线程 → GUI 线程的批准请求桥（queued，跨线程安全）
    _approval_requested = Signal(str, str, str, object)

    def __init__(self, store: PlatformStore, *, client=None, models=None, storage_preferences=None):
        super().__init__()
        configure_fonts()
        self.store = store
        self.storage_preferences = storage_preferences
        self._permission_mode_memory = 'risk'
        self.last_turn_envelope = None
        self.browser_panel = None
        self.client, self.models = client, models or []
        self.registry = SkillRegistry()
        for skill in BUILTINS:
            self.registry.register(skill)
        self.project_id = self.session_id = self.run_id = None
        self._draft_binding = None
        self._unsaved_drafts = {}
        self.task_manager = TaskManager()
        self.monitor = None
        self.version_worker = None
        self.update_worker = None
        self.available_update = None
        self._close_after_update = False
        self._local_chain = None
        self._agent_worker = None  # S15：新 Agent 路径轮次 Worker（不占用 task_manager）
        # S30：新 Agent worker 按会话隔离；_agent_worker 仅保留为当前会话兼容别名。
        self._agent_jobs = {}
        self._close_after_agent_jobs = False
        # S6-02：优雅关闭——宽限期计时与强制关闭标记
        self._close_grace_seconds = 15.0
        self._force_close = False
        self._close_grace_timer = QTimer(self)
        self._close_grace_timer.setSingleShot(True)
        self._close_grace_timer.timeout.connect(self._force_close_with_checkpoints)
        self._agent_session_id = None
        # 新 Agent 的增量文本先在内存中合并，再以低频刷新到对话面板。
        # 逐 token 调用 setHtml 会把 GUI 事件队列塞满，长回复看起来就像“卡死”。
        self._live_agent_text = ''
        # S6-01：每会话独立 live render state——timer 只是节流器，
        # 待刷新状态按 session 记账，互不干扰。
        self._live_render_pending: set = set()
        self._live_render_timer = QTimer(self)
        self._live_render_timer.setSingleShot(True)
        self._live_render_timer.setInterval(80)
        self._live_render_timer.timeout.connect(self._flush_live_agent_render)
        # S9：运行状态卡 elapsed/last-activity 每秒刷新；
        # 仅在有活跃任务时走表，不用 polling 伪造进度。
        self._status_timer = QTimer(self)
        self._status_timer.setInterval(1000)
        self._status_timer.timeout.connect(self._tick_run_status)
        # S10：执行记录折叠展开状态（内存态，随会话切换自然隔离）
        self._expanded_event_groups: set = set()
        self._last_event_group_keys: list = []
        self._feature_flags_cache = None
        # S16：会话/轮次状态控制器 + 当前轮次锚点（替代固定状态栏）
        from .conversation_status import ConversationStatusController

        self.status_controller = ConversationStatusController()
        self._agent_operation_id = None
        self._agent_user_message_id = None
        self._agent_user_text = ''
        self._file_rows = []
        self._file_records = {}
        self._artifact_entries = []
        self._task_records = []
        self._approval_requested.connect(self._handle_approval_request)
        self.network_state = "connected"
        self.setWindowTitle(
            "ZQ 技术平台" + (" · 本地交互预览" if client is None else "")
        )
        self.resize(1440, 900)
        self.setMinimumSize(960, 640)
        self._build()
        self.composer.textChanged.connect(self.save_current_draft)
        self.files.itemChanged.connect(self.save_current_draft)
        self.server_url = SERVER_URL
        self.session_badge_timer = QTimer(self)
        self.session_badge_timer.setInterval(1000)
        self.session_badge_timer.timeout.connect(self.refresh_session_badges)
        self.session_badge_timer.start()
        self.reload_projects(self.store.last_project if isinstance(self.store, ProjectCatalog) else None)

    @property
    def worker(self):
        """Current conversation's worker; background workers live in TaskManager."""
        return self.task_manager.for_session(self.store.owner, self.project_id, self.session_id)

    def button(self, title, callback, layout):
        button = QPushButton(title)
        button.clicked.connect(callback)
        layout.addWidget(button)
        return button

    def agent_permission_mode(self) -> str:
        if self.storage_preferences is None:
            return self._permission_mode_memory
        try:
            return self.storage_preferences.permission_mode(self.store.owner)
        except (ValueError, OSError, sqlite3.Error):
            return 'risk'

    def refresh_permission_menu(self) -> None:
        from .agent_permission_modes import permission_mode_options

        mode = self.agent_permission_mode()
        selected = next(item for item in permission_mode_options() if item.id == mode)
        self.permission_button.setText(selected.title)
        self.permission_button.setToolTip(selected.description)
        menu = self.permission_button.menu()
        menu.clear()
        for item in permission_mode_options():
            action = menu.addAction(f'{item.title}  —  {item.description}')
            action.setCheckable(True)
            action.setChecked(item.id == mode)
            action.triggered.connect(
                lambda _checked=False, value=item.id: self.set_agent_permission_mode(value)
            )

    def set_agent_permission_mode(self, mode: str) -> None:
        from .agent_permission_modes import validate_permission_mode

        mode = validate_permission_mode(mode)
        if self.storage_preferences is None:
            self._permission_mode_memory = mode
        else:
            try:
                self.storage_preferences.set_permission_mode(self.store.owner, mode)
            except (ValueError, OSError, sqlite3.Error):
                self.status.setText('权限模式保存失败，已保留原设置。')
                return
        stopped = self.task_manager.cancel_all()
        for job in list(self._agent_jobs.values()):
            try:
                job['gateway'].stop()
                stopped += 1
            except Exception:
                continue
        revoked = (self.browser_panel.task_leases.revoke_all()
                   if self.browser_panel is not None else 0)
        self.refresh_permission_menu()
        suffix = (f'；已停止 {stopped} 个任务并撤销 {revoked} 个浏览器接管'
                  if stopped or revoked else '')
        self.status.setText(f'已切换为“{self.permission_button.text()}”{suffix}。')

    def agent_operation_allowed(self, operation: str, title: str, text: str) -> bool:
        from .agent_permission_modes import requires_confirmation

        if not requires_confirmation(self.agent_permission_mode(), operation):
            return True
        return QMessageBox.question(
            self, title, text,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        ) == QMessageBox.StandardButton.Yes

    def generation_consent_required(self) -> bool:
        from .agent_permission_modes import requires_confirmation

        return requires_confirmation(self.agent_permission_mode(), 'generate_file')

    # ------------------------------------------------------------ 新 Agent 接线
    # 正式客户端只允许新 Agent；旧路由仅保留在源码中供迁移审计，不作为运行时回退。

    def _feature_flags(self):
        from .agent_switch import flags_store_for
        from .flags import FeatureFlagStore

        cache = self._feature_flags_cache
        if cache is not None and cache.path is not None:
            return cache
        try:
            resolved = flags_store_for(self.store)
        except ValueError:
            # ProjectCatalog 未激活（尚未创建/打开项目）：退回内存开关，
            # 项目激活后下一次访问自动重新绑定持久化文件
            if cache is None:
                cache = FeatureFlagStore()
                self._feature_flags_cache = cache
            return cache
        if cache is not None:  # 内存期勾选迁移进项目持久化文件
            for category, on in cache.snapshot().items():
                if on:
                    resolved.set_enabled(category, True)
        self._feature_flags_cache = resolved
        return resolved

    def refresh_grayscale_menu(self) -> None:
        from .agent_switch import FLAG_LABELS, enabled_count
        from .flags import FEATURE_FLAG_ORDER

        flags = self._feature_flags()
        menu = self.grayscale_button.menu()
        menu.clear()
        for category in FEATURE_FLAG_ORDER:
            action = menu.addAction(FLAG_LABELS[category])
            action.setCheckable(True)
            action.setChecked(flags.enabled(category))
            action.triggered.connect(
                lambda _checked=False, key=category, item=action:
                    self.set_grayscale_flag(key, item.isChecked())
            )
        total = len(FEATURE_FLAG_ORDER)
        self.grayscale_button.setText(f'灰度：新路径 {enabled_count(flags)}/{total}')
        self.grayscale_button.setToolTip(
            '逐类切换到新 Agent 内核；默认全部关闭（旧路径），可随时退回。')

    def set_grayscale_flag(self, category: str, enabled: bool) -> None:
        from .agent_switch import FLAG_LABELS

        self._feature_flags().set_enabled(category, enabled)
        self.refresh_grayscale_menu()
        target = '新路径' if enabled else '旧路径'
        self.status.setText(f'灰度开关：{FLAG_LABELS[category]} → {target}。')

    def _make_agent_gateway(self):
        """装配新 Agent 网关；未连接服务端时返回 None，由调用方展示可行动失败。"""
        from .agent_gateway import AgentGateway
        from .agent_switch import ApproverBridge, client_model_port_factory

        try:
            model_factory = client_model_port_factory(
                self.client, client_version=CLIENT_VERSION)
        except ValueError:
            self.status.setText('新 Agent 需要先连接服务端；本轮未发送。')
            return None
        model_id = self.model_combo.currentData()
        provider_factory = None
        if model_id:
            from .model_port.provider_factory import production_provider_factory

            provider_factory = production_provider_factory(self.client, model_id)
        browser_backend = getattr(self.browser_panel, 'agent_backend', None)
        gateway = AgentGateway(
            self.store, self.session_id,
            flags=self._feature_flags(), model_id=model_id or '',
            model_port_factory=model_factory,
            permission_mode_getter=self.agent_permission_mode,
            provider_factory=provider_factory,
            browser_backend=browser_backend,
            approver=ApproverBridge(self._ask_approval_gui),
            force_all_tools=True)
        self._agent_gateway = gateway
        return gateway

    def _try_agent_submit(self, prompt: str, file_ids=(), upload_ids=()) -> bool:
        """生产客户端只使用新 Agent；连接不完整时阻止旧路径接管。"""
        if self.session_id in self._agent_jobs:
            return True  # 当前会话已有轮次；其他会话可以并行运行
        gateway = self._make_agent_gateway()
        if gateway is None:
            self.status.setText('新 Agent 尚未连接服务端，本轮未发送；请先连接并重试。')
            return True
        self._agent_gateway = gateway
        from .agent_switch import AgentTurnWorker

        # 新 Agent 的 begin_operation 原子地写入 user_message。不要再向
        # legacy store.messages 灰期双写，否则同一轮会在 UI 出现两次。
        self._agent_user_message_id = None
        self._agent_user_text = prompt
        # Test doubles and third-party gateway adapters may not expose the
        # durable Agent repository. Keep their legacy fallback visible; the
        # production gateway persists the same entry atomically and therefore
        # must not receive this second write.
        if not hasattr(gateway, 'repo'):
            self._agent_user_message_id = self.store.append(
                self.session_id, 'user', prompt)
        # S1-03：UI 不再自造假 operation id；真实 durable id 由 worker 的
        # accepted 信号带回（operation_accepted 事件）后再登记状态控制器。
        self._agent_operation_id = None
        worker = AgentTurnWorker(gateway, prompt, parent=self,
                                 file_ids=tuple(file_ids),
                                 upload_ids=tuple(upload_ids))
        session_id = self.session_id
        worker.accepted.connect(lambda op_id, sid=session_id:
                                self._on_agent_accepted_for(sid, op_id))
        worker.delta.connect(lambda text, sid=session_id:
                             self._on_agent_delta_for(sid, text))
        worker.done.connect(lambda result, sid=session_id:
                            self._on_agent_done_for(sid, result))
        worker.finished.connect(lambda sid=session_id:
                                self._on_agent_worker_finished_for(sid))
        now = time.monotonic()
        self._agent_jobs[session_id] = {
            'worker': worker, 'gateway': gateway,
            'operation_id': None, 'user_text': prompt,
            'live_text': '',
            # S9：真实计时锚点（单调时钟）与停止标记
            'started_at': now, 'last_activity_at': now,
            'stop_requested': False,
        }
        self._agent_worker = worker
        self._agent_session_id = session_id
        self._live_agent_text = ''
        self.composer.clear()
        self.set_busy(True)
        self.status.setText('新 Agent 路径：正在生成…')
        self.render_messages()  # 用户消息 + live 状态卡立即进入时间线
        worker.start()
        self._pending_upload_ids = set()  # 本轮上传已随消息冻结进 operation
        return True

    def _on_agent_accepted_for(self, session_id: str | None,
                               operation_id: str) -> None:
        """S1-03：operation_accepted 带回真实 durable id 后登记轮次状态。"""
        if not session_id or not operation_id:
            return
        job = self._agent_jobs.get(session_id)
        if job is not None:
            job['operation_id'] = operation_id
            job['last_activity_at'] = time.monotonic()
        if session_id == self.session_id:
            self._agent_operation_id = operation_id
        self.status_controller.set_turn_phase(
            session_id, operation_id, '新 Agent 路径：正在生成…')
        if session_id == self.session_id:
            if not self._status_timer.isActive():
                self._status_timer.start()
            self.render_messages()

    def _on_agent_delta(self, text: str) -> None:
        self._on_agent_delta_for(self._agent_session_id or self.session_id, text)

    def _on_agent_delta_for(self, session_id: str | None, text: str) -> None:
        if text:
            job = self._agent_jobs.get(session_id)
            if job is None:
                return
            job['live_text'] += text
            job['last_activity_at'] = time.monotonic()
            self._live_render_pending.add(session_id)
            if session_id == self.session_id:
                self._live_agent_text = job['live_text']
            # 只把“正在生成”状态写到状态栏；正文在对话面板中增量显示。
            if self.session_id == session_id:
                self.status.setText('新 Agent 路径：正在生成…')
            if (self.session_id == session_id
                    and not self._live_render_timer.isActive()):
                self._live_render_timer.start()

    def _flush_live_agent_render(self) -> None:
        # S6-01：只冲刷当前会话的待刷新记账；后台会话的 live text
        # 在 job 内持续累积，切回时由 choose_session 一次性呈现。
        current = self.session_id
        if current not in self._live_render_pending:
            return
        self._live_render_pending.discard(current)
        job = self._agent_jobs.get(current)
        if job is not None:
            self._live_agent_text = job['live_text']
            self.render_messages()

    def _on_agent_done(self, result: dict) -> None:
        self._on_agent_done_for(self._agent_session_id or self.session_id, result)

    def _on_agent_done_for(self, session_id: str | None, result: dict) -> None:
        # S6-01：只清除本会话的待刷新记账；其他会话仍在流式时
        # 绝不停掉 timer，否则后台会话完成会冻结当前会话的实时刷新。
        self._live_render_pending.discard(session_id)
        if (session_id == self.session_id
                and self.session_id not in self._live_render_pending):
            self._live_render_timer.stop()
        job = self._agent_jobs.get(session_id)
        if job is None:
            return
        if session_id == self.session_id:
            self._live_agent_text = ''
        reply = (result.get('reply') or '').strip()
        if not reply:
            reason = (result.get('error_message') or result.get('error_code')
                      or result.get('status') or '未知原因')
            reply = f'本轮未完成：{reason}。'
        target_session = session_id
        # S1-03：优先使用 gateway 返回的真实 durable operation id。
        operation_id = result.get('operation_id') or job.get('operation_id')
        if operation_id:
            job['operation_id'] = operation_id
        gateway = job.get('gateway')
        repo = getattr(gateway, 'repo', None)
        if target_session and repo is None:
            # 无 repo 的测试替身/第三方适配：保持旧的本地消息追加。
            self.store.append(target_session, 'assistant', reply)
        elif (target_session and repo is not None and operation_id
                and result.get('status') != 'completed'):
            # S1-04：先查本轮 operation 是否已有 terminal assistant/error
            # entry；没有才追加 fallback，不得只凭 hasattr(repo) 跳过。
            terminal = [e for e in repo.entries(target_session, 'main')
                        if e.operation_id == operation_id
                        and e.entry_type in ('assistant_message',
                                             'error_message')
                        and not e.payload.get('intermediate')]
            if not terminal:
                try:
                    repo.append_entry(
                        target_session, 'main', 'error_message',
                        {'text': reply,
                         'error_code': result.get('error_code') or 'failed',
                         'fallback': True},
                        operation_id=operation_id)
                except Exception:  # UI 兜底不得再次失败
                    import logging
                    logging.getLogger(__name__).warning(
                        'fallback 错误 Entry 写入失败', exc_info=True)
        # S16：终态只进轮次控制器与消息表；禁止把完整回复写进状态控件
        if operation_id and target_session:
            if result.get('status') == 'completed':
                self.status_controller.complete_turn(
                    target_session, operation_id, reply)
            elif result.get('status') == 'aborted':
                self.status_controller.cancel_turn(
                    target_session, operation_id, reply)
            else:
                self.status_controller.fail_turn(
                    target_session, operation_id,
                    result.get('error_code') or 'failed', reply)
        if session_id == self.session_id:
            self._agent_operation_id = None  # 终态已定：live 状态卡退出时间线
        job['done'] = True
        if self.session_id == target_session:
            self.render_messages()

    def _on_agent_worker_finished(self) -> None:
        self._on_agent_worker_finished_for(self._agent_session_id or self.session_id)

    def _on_agent_worker_finished_for(self, session_id: str | None) -> None:
        self._agent_jobs.pop(session_id, None)
        if not self._agent_jobs and self._status_timer.isActive():
            self._status_timer.stop()
        if session_id != self.session_id:
            if self._close_after_agent_jobs and not self._agent_jobs:
                self._close_after_agent_jobs = False
                QTimer.singleShot(0, self.close)
            return
        self._agent_worker = None
        self._agent_session_id = None
        self._agent_operation_id = None
        self._agent_user_message_id = None
        self._agent_user_text = ''
        self.set_busy(False)
        if self._close_after_agent_jobs and not self._agent_jobs:
            self._close_after_agent_jobs = False
            QTimer.singleShot(0, self.close)

    def _ask_approval_gui(self, operation: str, title: str, reason: str) -> bool:
        """ApproverBridge 在 Worker 线程内调用；转到 GUI 线程弹旧批准框。"""
        if QThread.currentThread() is self.thread():
            return self.agent_operation_allowed(operation, title, reason)
        verdict = {}
        ready = threading.Event()

        def callback(ok) -> None:
            verdict['ok'] = bool(ok)
            ready.set()

        self._approval_requested.emit(operation, title, reason, callback)
        # A closed/hidden dialog must not leave the worker or UI blocked
        # forever.  Timeout is fail-closed; a late callback is ignored.
        if not ready.wait(timeout=300):
            return False
        return verdict.get('ok', False)

    def _handle_approval_request(self, operation: str, title: str, reason: str,
                                 callback) -> None:
        callback(self.agent_operation_allowed(operation, title, reason))

    def _build(self):
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setHandleWidth(1)
        self.setCentralWidget(splitter)
        sidebar = QWidget()
        self.sidebar = sidebar
        sidebar.setObjectName("sidebar")
        left = QVBoxLayout(sidebar)
        left.setContentsMargins(16, 22, 16, 18)
        left.setSpacing(8)
        brand = QLabel("ZQ  <span style='font-weight:400'>Workspace</span>")
        brand.setObjectName("brand")
        left.addWidget(brand)
        subtitle = QLabel("项目驱动的智能工作空间")
        subtitle.setObjectName("muted")
        left.addWidget(subtitle)
        left.addSpacing(24)
        self.button("＋  新建项目", self.new_project, left).setObjectName("newProject")
        self.button("打开已有项目 / 重新定位", self.open_project_directory, left)
        left.addSpacing(20)
        # Retain the existing selection controllers while the visible navigation
        # is unified in ProjectTree; these lists are not additional UI surfaces.
        self.projects = QListWidget(self)
        self.projects.hide()
        self.projects.setMaximumHeight(180)
        self.projects.currentItemChanged.connect(self.choose_project)
        left.addSpacing(12)
        session_header = QHBoxLayout()
        heading = QLabel("项目与会话")
        heading.setObjectName("sectionLabel")
        session_header.addWidget(heading, 1)
        self.button("＋", self.new_session, session_header).setToolTip("新建会话")
        left.addLayout(session_header)
        self.sessions = QListWidget(self)
        self.sessions.hide()
        self.sessions.currentItemChanged.connect(self.choose_session)
        self.sessions.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.sessions.customContextMenuRequested.connect(self.session_menu)
        from .project_tree import ProjectTree
        self.project_tree = ProjectTree(self)
        self.project_tree.currentItemChanged.connect(self.choose_tree_item)
        self.project_tree.itemClicked.connect(self.project_tree_action)
        self.project_tree.customContextMenuRequested.connect(self.tree_menu)
        left.addWidget(self.project_tree, 3)
        self.button("工具与能力", self.manage_skills, left).setObjectName("mutedButton")
        self.more_button = QPushButton("更多", self)
        self.more_button.setObjectName("mutedButton")
        more_menu = QMenu(self.more_button)
        more_menu.addAction("恢复已归档会话", self.restore_session)
        more_menu.addAction("恢复已归档项目", self.restore_project)
        more_menu.addAction("认领旧共享项目", self.claim_legacy_project)
        more_menu.addAction("检查服务版本兼容性", self.check_versions)
        self.more_button.setMenu(more_menu)
        left.addWidget(self.more_button)
        left.addSpacing(12)
        account = QLabel(
            "●  本地预览 <span style='color:#a5a7ae'> / 只读模式</span>"
            if self.client is None
            else "●  审核服务已连接"
        )
        account.setObjectName("account")
        left.addWidget(account)
        self.account_label = account
        self.button("连接 / 登录模型服务", self.connect_service, left)
        self.version_label = QLabel(f"客户端 {CLIENT_VERSION} · 审核工具 {REVIEW.version}")
        self.version_label.setWordWrap(True)
        left.addWidget(self.version_label)
        self.update_button = self.button("下载并安装更新", self.install_update, left)
        self.update_button.hide()
        splitter.addWidget(sidebar)

        center = QWidget()
        middle = QVBoxLayout(center)
        middle.setContentsMargins(32, 18, 32, 22)
        middle.setSpacing(14)
        top = QHBoxLayout()
        self.title = QLabel("创建项目，开始工作")
        self.title.setObjectName("title")
        top.addWidget(self.title, 1)
        panel_button = self.button("项目面板", self.toggle_details, top)
        panel_button.setObjectName("panelButton")
        panel_button.setToolTip("显示或隐藏项目面板（文件 / 记忆 / 成果 / 任务）")
        self.button('浏览器', self.toggle_browser, top).setToolTip('显示或隐藏独立浏览器')
        middle.addLayout(top)
        self.project_summary = QLabel("")
        self.project_summary.setObjectName("muted")
        self.project_summary.setVisible(False)
        middle.addWidget(self.project_summary)
        self.transcript = QTextBrowser()
        self.transcript.setObjectName("transcript")
        self.transcript.setOpenExternalLinks(False)
        self.transcript.setOpenLinks(False)
        self.transcript.anchorClicked.connect(self.handle_report_link)
        middle.addWidget(self.transcript, 1)
        self.status = QLabel("")
        self.status.setObjectName("status")
        self.status.setWordWrap(True)
        # S16：固定状态栏退出布局。status 仅作不可见适配器保留，
        # 旧调用点（setText）不再向用户展示；轮次状态由时间线承载。
        self.status.setVisible(False)
        composer_card = QWidget()
        composer_card.setObjectName("composerCard")
        composer_layout = QVBoxLayout(composer_card)
        composer_layout.setContentsMargins(12, 10, 12, 10)
        composer_layout.setSpacing(4)
        self.composer = ChatComposer()
        self.composer.setObjectName("composer")
        self.composer.setFixedHeight(86)
        self.composer.setPlaceholderText(
            "描述你想完成的工作…\nEnter 发送 · Alt+Enter 换行"
        )
        composer_layout.addWidget(self.composer)
        actions = QHBoxLayout()
        self.attach = self.button("＋", self.add_files, actions)
        self.attach.setToolTip("添加项目文件")
        self.attach.setFixedWidth(36)
        actions.addWidget(QLabel('Agent 自动选择任务能力'))
        actions.addStretch(1)
        self.model_combo = QComboBox()
        for model in self.models:
            self.model_combo.addItem(model["display_name"], model["model_id"])
        self.model_combo.setVisible(self.client is not None)
        actions.addWidget(self.model_combo)
        self.permission_button = QPushButton(self)
        self.permission_button.setAccessibleName('选择 Agent 权限模式')
        self.permission_button.setMenu(QMenu(self.permission_button))
        actions.addWidget(self.permission_button)
        self.refresh_permission_menu()
        self.grayscale_button = QPushButton(self)
        self.grayscale_button.setAccessibleName('新 Agent 灰度开关')
        self.grayscale_button.setMenu(QMenu(self.grayscale_button))
        actions.addWidget(self.grayscale_button)
        self.refresh_grayscale_menu()
        self.grayscale_button.hide()
        self.stop = self.button("停止", self.cancel_run, actions)
        self.stop.setEnabled(False)
        self.send = self.button("执行 ↑", self.submit, actions)
        self.composer.send_requested.connect(self.send.click)
        self.send.setToolTip('发送消息（Enter）；输入框内 Alt+Enter 换行')
        self.send.setObjectName("sendButton")
        composer_layout.addLayout(actions)
        middle.addWidget(composer_card)
        hint = QLabel(
            "原始文件只读 · 预检不会调用模型或产生费用"
            if self.client is None
            else "原始文件只读 · 模型用量由服务端结算"
        )
        hint.setObjectName("footerHint")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        middle.addWidget(hint)
        self.drop_center = center
        for target in [center, *center.findChildren(QWidget)]:
            target.setAcceptDrops(True)
            target.installEventFilter(self)
        splitter.addWidget(center)

        self.details = QTabWidget()
        self.details.setMinimumWidth(250)
        self.files = QListWidget()
        self.files.setObjectName("fileList")
        file_page = QWidget()
        file_layout = QVBoxLayout(file_page)
        file_layout.setContentsMargins(18, 22, 18, 16)
        file_layout.setSpacing(12)
        file_title = QLabel("项目资料")
        file_title.setObjectName("detailTitle")
        file_layout.addWidget(file_title)
        caption = QLabel("资料仅在本地读取\n隐藏工作表会自动排除")
        caption.setObjectName("muted")
        file_layout.addWidget(caption)
        self.file_search = QLineEdit()
        self.file_search.setObjectName("fileSearch")
        self.file_search.setPlaceholderText("搜索文件名")
        self.file_search.setClearButtonEnabled(True)
        file_layout.addWidget(self.file_search)
        self.file_filter = QComboBox()
        self.file_filter.setObjectName("fileFilter")
        self.file_filter.addItems(["全部文件", "本轮已选", "未使用", "已用于任务"])
        file_layout.addWidget(self.file_filter)
        batch_row = QHBoxLayout()
        self.file_select_visible = QPushButton("全选可见")
        self.file_clear_visible = QPushButton("取消可见")
        batch_row.addWidget(self.file_select_visible)
        batch_row.addWidget(self.file_clear_visible)
        file_layout.addLayout(batch_row)
        file_layout.addWidget(self.files, 1)
        self.file_detail = QLabel("双击文件查看详情")
        self.file_detail.setObjectName("muted")
        self.file_detail.setWordWrap(True)
        file_layout.addWidget(self.file_detail)
        self.details.addTab(file_page, "文件")
        self.file_search.textChanged.connect(self._apply_file_filter)
        self.file_filter.currentIndexChanged.connect(self._apply_file_filter)
        self.file_select_visible.clicked.connect(self.select_visible_files)
        self.file_clear_visible.clicked.connect(self.clear_visible_files)
        self.files.itemDoubleClicked.connect(self.show_file_detail)
        memory_page = QWidget()
        memory_layout = QVBoxLayout(memory_page)
        memory_layout.addWidget(
            QLabel("仅保存本项目明确确认的偏好\n请勿填写原文或隐藏工作表内容")
        )
        self.memories = QListWidget()
        memory_layout.addWidget(self.memories)
        self.button("添加已确认偏好", self.add_memory, memory_layout)
        self.button("删除选中记忆", self.delete_memory, memory_layout)
        self.details.addTab(memory_page, "记忆")
        artifacts_page = QWidget()
        artifacts_layout = QVBoxLayout(artifacts_page)
        artifacts_layout.setContentsMargins(18, 22, 18, 16)
        artifacts_layout.setSpacing(12)
        artifacts_title = QLabel("成果交付")
        artifacts_title.setObjectName("detailTitle")
        artifacts_layout.addWidget(artifacts_title)
        self.artifacts_list = QListWidget()
        self.artifacts_list.setObjectName("artifactsList")
        artifacts_layout.addWidget(self.artifacts_list, 1)
        artifact_buttons = QHBoxLayout()
        self.artifact_open = QPushButton("打开成果")
        self.artifact_save = QPushButton("另存为…")
        artifact_buttons.addWidget(self.artifact_open)
        artifact_buttons.addWidget(self.artifact_save)
        artifacts_layout.addLayout(artifact_buttons)
        self.details.addTab(artifacts_page, "成果")
        tasks_page = QWidget()
        tasks_layout = QVBoxLayout(tasks_page)
        tasks_layout.setContentsMargins(18, 22, 18, 16)
        tasks_layout.setSpacing(12)
        tasks_title = QLabel("任务历史")
        tasks_title.setObjectName("detailTitle")
        tasks_layout.addWidget(tasks_title)
        self.tasks_list = QListWidget()
        self.tasks_list.setObjectName("tasksList")
        tasks_layout.addWidget(self.tasks_list, 1)
        self.task_detail = QLabel("双击任务查看详情")
        self.task_detail.setObjectName("muted")
        self.task_detail.setWordWrap(True)
        tasks_layout.addWidget(self.task_detail)
        self.details.addTab(tasks_page, "任务")
        splitter.addWidget(self.details)
        self.artifact_open.clicked.connect(self.open_selected_artifact)
        self.artifact_save.clicked.connect(self.save_artifact_as)
        self.artifacts_list.itemDoubleClicked.connect(
            lambda _item: self.open_selected_artifact())
        self.tasks_list.itemDoubleClicked.connect(self.show_task_detail)
        splitter.setSizes([242, 886, 312])
        splitter.setCollapsible(1, False)
        self.setStyleSheet("""
            QMainWindow, QWidget { background:#ffffff; color:#282b33; font-size:13px; }
            QWidget#sidebar { background:#f5f5f7; }
            QWidget#sidebar QLabel { background:transparent; }
            QLabel#brand { font-size:21px; font-weight:700; padding:4px 2px; }
            QLabel#muted { color:#8a8e99; font-size:12px; line-height:160%; }
            QLabel#sectionLabel { color:#9497a1; font-size:11px; padding-left:6px; }
            QLabel#title { font-size:15px; font-weight:600; padding:8px 0; }
            QLabel#account { color:#727782; font-size:11px; padding:12px 4px; border-top:1px solid #e5e6eb; }
            QLabel#status { color:#858a95; font-size:11px; padding-left:10px; }
            QLabel#footerHint { color:#a0a4ad; font-size:10px; }
            QLabel#detailTitle { font-size:14px; font-weight:600; }
            QListWidget, QTreeWidget#projectTree { border:0; background:transparent; outline:0; padding:0; }
            QListWidget::item, QTreeWidget#projectTree::item { padding:11px 10px; border-radius:8px; margin:2px 0; }
            QListWidget::item:hover, QTreeWidget#projectTree::item:hover { background:#ededf1; }
            QListWidget::item:selected, QTreeWidget#projectTree::item:selected { background:#e7e8ee; color:#252a37; }
            QTreeWidget#projectTree { show-decoration-selected:0; selection-background-color:#e7e8ee; }
            QListWidget#fileList::item { background:#f8f9fb; border:1px solid #edf0f4; margin:4px 0; padding:14px 10px; }
            QTextBrowser#transcript { background:white; border:0; padding:12px 6px; }
            QTextBrowser#result { background:white; border:0; padding:20px; }
            QWidget#composerCard { background:#fafafb; border:1px solid #e1e3ea; border-radius:16px; }
            QTextEdit#composer { background:transparent; border:0; padding:6px; font-size:14px; selection-background-color:#dce6fb; }
            QPushButton { background:transparent; border:0; border-radius:7px; padding:8px 12px; }
            QPushButton:hover { background:#edeef3; }
            QPushButton:pressed { background:#e2e5ed; }
            QPushButton:disabled { color:#b0b3bd; }
            QPushButton#newProject { background:#fff; border:1px solid #e4e5eb; text-align:left; padding:11px; }
            QPushButton#newProject:hover { background:#eceef5; }
            QPushButton#mutedButton { color:#9397a2; text-align:left; }
            QPushButton#panelButton { border:1px solid #e8e9ee; color:#727783; padding:7px 12px; }
            QPushButton#sendButton { background:#2d3342; color:white; padding:9px 18px; border-radius:9px; font-weight:600; }
            QPushButton#sendButton:hover { background:#424c63; }
            QPushButton#sendButton:disabled { background:#ccd0d9; color:#f7f8fa; }
            QComboBox { background:#f0f1f5; border:0; border-radius:6px; padding:6px 12px; min-width:92px; color:#656b79; }
            QComboBox::drop-down { border:0; width:18px; }
            QComboBox QAbstractItemView { background:white; selection-background-color:#eceef6; color:#303744; }
            QTabWidget::pane { border:0; border-left:1px solid #eceef2; }
            QTabBar::tab { background:white; padding:18px 22px 14px; color:#9398a4; border-bottom:2px solid transparent; }
            QTabBar::tab:selected { color:#333b4c; border-bottom:2px solid #586783; }
            QSplitter::handle { background:#edeef2; }
            QScrollBar:vertical { background:transparent; width:5px; margin:2px; }
            QScrollBar::handle:vertical { background:#d9dce4; border-radius:2px; min-height:30px; }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height:0; }
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background:transparent; }
        """)

    def reload_projects(self, selected=None):
        self.projects.clear()
        for project in self.store.projects():
            item = QListWidgetItem(project["name"] + (" · 目录不可用" if project.get("unavailable") else ""))
            item.setData(Qt.ItemDataRole.UserRole, project["id"])
            self.projects.addItem(item)
            if project["id"] == selected:
                self.projects.setCurrentItem(item)
        self.projects.setFixedHeight(max(52, min(5, self.projects.count()) * 46))
        self.refresh_project_tree()

    def refresh_project_tree(self):
        self.project_tree.refresh(self.store, self.task_manager, self.project_id, self.session_id)

    def choose_tree_item(self, item, _previous=None):
        if item is None:
            return
        project, session = item.data(0, Qt.ItemDataRole.UserRole)
        if project != self.project_id:
            for index in range(self.projects.count()):
                row = self.projects.item(index)
                if row.data(Qt.ItemDataRole.UserRole) == project:
                    self.projects.setCurrentItem(row)
                    break
        if self.project_id == project and session is not None:
            for index in range(self.sessions.count()):
                row = self.sessions.item(index)
                if row.data(Qt.ItemDataRole.UserRole) == session:
                    self.sessions.setCurrentItem(row)
                    break

    def tree_menu(self, position):
        item = self.project_tree.itemAt(position)
        if item is None:
            return
        project, session = item.data(0, Qt.ItemDataRole.UserRole)
        self.project_tree.setCurrentItem(item)
        menu = QMenu(self)
        if session is None:
            menu.addAction('重命名项目', lambda: self.rename_project(project))
            if isinstance(self.store, ProjectCatalog):
                record = next((row for row in self.store.projects() if row['id'] == project), None)
                pinned = bool(record and record.get('pinned'))
                menu.addAction('取消置顶' if pinned else '置顶',
                               lambda: self.pin_project(project, not pinned))
            menu.addAction('归档项目', lambda: self.archive_project(project))
            if isinstance(self.store, ProjectCatalog):
                menu.addAction('从侧栏移除', lambda: self.remove_project(project))
        elif self.project_id == project:
            menu.addAction('新建会话', self.new_session)
        if session is not None and self.project_id == project and self.session_id == session:
            menu.addAction('重命名会话', self.rename_session)
            menu.addAction('归档会话', self.archive_session)
        menu.exec(self.project_tree.viewport().mapToGlobal(position))

    def project_tree_action(self, item, column):
        project, session = item.data(0, Qt.ItemDataRole.UserRole)
        if session is not None:
            return
        if column == 1:
            self.rename_project(project)
        elif column == 2:
            self.tree_menu(self.project_tree.visualItemRect(item).center())

    def rename_project(self, project):
        current = next((row for row in self.store.projects() if row['id'] == project), None)
        if current is None:
            return
        name, accepted = QInputDialog.getText(self, '重命名项目', '项目名称', text=current['name'])
        if not accepted:
            return
        try:
            self.store.rename_project(project, name)
            self.reload_projects(project if self.project_id == project else self.project_id)
        except (ValueError, PermissionError, OSError, sqlite3.Error) as exc:
            self.status.setText(str(exc))

    def pin_project(self, project, pinned):
        try:
            self.store.set_pinned(project, pinned)
            self.reload_projects(self.project_id)
        except (ValueError, PermissionError, OSError, sqlite3.Error) as exc:
            self.status.setText(str(exc))

    def archive_project(self, project):
        if self.task_manager.active():
            self.status.setText('仍有任务运行，暂不能归档项目。')
            return
        try:
            target = self.store.project_store(project) if isinstance(self.store, ProjectCatalog) else self.store
            target.archive(project)
            self.reload_projects()
        except (ValueError, PermissionError, OSError, sqlite3.Error) as exc:
            self.status.setText(str(exc))

    def remove_project(self, project):
        if self.task_manager.active():
            self.status.setText('仍有任务运行，暂不能移除项目。')
            return
        if QMessageBox.question(
            self, '从侧栏移除项目', '仅移除本机侧栏登记，不删除项目目录、资料、会话或成果。确认继续？',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        ) != QMessageBox.StandardButton.Yes:
            return
        try:
            self.store.remove_from_sidebar(project)
            if self.project_id == project:
                self.project_id = self.session_id = self.run_id = None
            self.reload_projects()
            self.status.setText('已从侧栏移除；可通过“打开已有项目”重新登记，项目文件未删除。')
        except (ValueError, PermissionError, OSError, sqlite3.Error) as exc:
            self.status.setText(str(exc))

    def new_project(self):
        name, ok = QInputDialog.getText(self, "新建项目", "项目名称")
        if ok and name.strip():
            try:
                if isinstance(self.store, ProjectCatalog):
                    selected = QFileDialog.getExistingDirectory(self, "选择非系统盘项目文件夹", "")
                    if not selected:
                        return
                    identity = self.store.create_project(name, Path(selected))
                else:
                    identity = self.store.create_project(name)
            except (OSError, ValueError) as exc:
                self.status.setText(str(exc))
                return
            self.store.create_session(identity)
            self.reload_projects(identity)

    def open_project_directory(self):
        if not isinstance(self.store, ProjectCatalog):
            return
        selected = QFileDialog.getExistingDirectory(self, "打开已有项目或旧工作空间（非系统盘）", "")
        if not selected:
            return
        try:
            identities = self.store.open_directory(Path(selected))
            self.reload_projects(identities[0] if identities else None)
            if not identities:
                self.status.setText("目录中没有属于当前账号的项目；不会自动认领其他账号的数据。")
        except (OSError, ValueError, PermissionError) as exc:
            self.status.setText(str(exc))

    def choose_project(self, item, _previous=None):
        self._draft_binding = None
        self.session_id = None
        self.project_id = item.data(Qt.ItemDataRole.UserRole) if item else None
        blocker = QSignalBlocker(self.sessions)
        self.sessions.clear()
        del blocker
        self.files.clear()
        self.memories.clear()
        if not self.project_id:
            self.title.setText("创建项目，开始工作")
            self.composer.clear()
            self.run_id = None
            self.set_busy(False)
            self.render_messages()
            return
        if isinstance(self.store, ProjectCatalog):
            try:
                self.store.select_project(self.project_id)
            except (OSError, ValueError, PermissionError) as exc:
                self.project_id = self.session_id = None
                self.title.setText("项目目录不可用")
                self.status.setText(str(exc))
                self.render_messages()
                return
        self.title.setText(self.store.project(self.project_id)["name"])
        self.title.setToolTip(self.store.project(self.project_id)["name"])
        # S16：空会话说明由 transcript 空状态承载（render_messages），不再占用状态控件
        for session in self.store.sessions(self.project_id):
            row = QListWidgetItem(session["title"])
            row.setData(Qt.ItemDataRole.UserRole, session["id"])
            self.sessions.addItem(row)
        target_row = max(0, self.sessions.count() - 1)
        if isinstance(self.store, ProjectCatalog):
            remembered = self.store.last_session
            for i in range(self.sessions.count()):
                if self.sessions.item(i).data(Qt.ItemDataRole.UserRole) == remembered:
                    target_row = i
                    break
        self.sessions.setCurrentRow(target_row)
        self.refresh_details()

    def new_session(self):
        if self.project_id:
            identity = self.store.create_session(
                self.project_id, f"会话 {self.sessions.count() + 1}"
            )
            self.reload_sessions(identity)

    def session_menu(self, position):
        item = self.sessions.itemAt(position)
        if item is None:
            return
        self.sessions.setCurrentItem(item)
        menu = QMenu(self)
        menu.addAction('重命名会话', self.rename_session)
        menu.addAction('归档会话', self.archive_session)
        menu.exec(self.sessions.viewport().mapToGlobal(position))

    def reload_sessions(self, selected=None):
        self.sessions.clear()
        if not self.project_id:
            return
        for session in self.store.sessions(self.project_id):
            row = QListWidgetItem(session['title'])
            row.setData(Qt.ItemDataRole.UserRole, session['id'])
            self.sessions.addItem(row)
            if session['id'] == selected:
                self.sessions.setCurrentItem(row)
        if self.sessions.currentItem() is None and self.sessions.count():
            self.sessions.setCurrentRow(0)
        self.refresh_project_tree()

    def refresh_session_badges(self):
        from .navigation_snapshot import navigation_snapshot
        if not self.project_id:
            return
        try:
            snapshot = navigation_snapshot(self.store)
            project = next((p for p in snapshot if p['id'] == self.project_id), None)
            rows = {row['id']: row for row in project['sessions']} if project else {}
            for index in range(self.sessions.count()):
                item = self.sessions.item(index)
                identity = item.data(Qt.ItemDataRole.UserRole)
                row = rows.get(identity)
                if row is None:
                    continue
                labels = [row['title']]
                if self.task_manager.for_session(self.store.owner, self.project_id, identity) is not None:
                    labels.append('运行中')
                if row['unread_count']:
                    labels.append(f"未读 {row['unread_count']}")
                item.setText(' · '.join(labels))
            self.project_tree.refresh(self.store, self.task_manager, self.project_id,
                                      self.session_id, snapshot=snapshot)
        except (OSError, ValueError, PermissionError, sqlite3.Error):
            # A temporarily unavailable project must not break the Qt event loop.
            self.session_badge_timer.stop()
            self.status.setText('会话状态更新失败；请重新打开项目目录。')

    def rename_session(self):
        from .session_service import SessionService
        if not self.session_id:
            return
        identity = self.session_id
        title, ok = QInputDialog.getText(self, '重命名会话', '会话名称',
                                        text=self.store.session(identity)['title'])
        if ok:
            try:
                SessionService(self.store).rename(identity, title)
                self.reload_sessions(identity)
            except (OSError, ValueError, PermissionError, sqlite3.Error):
                self.status.setText('无法重命名会话，请检查名称和项目目录。')

    def archive_session(self):
        from .session_service import SessionService
        if not self.session_id:
            return
        if self.worker is not None:
            self.status.setText('请等待本会话任务结束后再归档。')
            return
        if QMessageBox.question(self, '归档会话', '归档当前会话？历史内容和成果保留，可随时恢复。') != QMessageBox.StandardButton.Yes:
            return
        try:
            SessionService(self.store).archive(self.session_id, True)
            self.reload_sessions()
        except (OSError, ValueError, PermissionError, sqlite3.Error):
            self.status.setText('会话未归档，请确认任务已结束且项目目录可用。')

    def restore_session(self):
        from .session_service import SessionService
        if not self.project_id:
            return
        try:
            service = SessionService(self.store)
            rows = service.list(self.project_id, archived=True)
            if not rows:
                self.status.setText('当前项目没有已归档会话。')
                return
            labels = [f"{i + 1}. {row['title']}" for i, row in enumerate(rows)]
            label, ok = QInputDialog.getItem(self, '恢复会话', '选择会话', labels, 0, False)
            if ok and label in labels:
                identity = rows[labels.index(label)]['id']
                service.archive(identity, False)
                self.reload_sessions(identity)
        except (OSError, ValueError, PermissionError, sqlite3.Error):
            self.status.setText('无法恢复会话，请检查项目目录。')

    def choose_session(self, item, _previous=None):
        from .session_service import SessionService
        from .task_recovery import reconcile_execution

        self._live_render_timer.stop()
        self._draft_binding = None
        self.session_id = item.data(Qt.ItemDataRole.UserRole) if item else None
        # S6-01：新会话的累积 live text 由下方 restore+render 一次性呈现，
        # 其待刷新记账随之结清；后台会话的记账保留，不受切换影响。
        self._live_render_pending.discard(self.session_id)
        current_job = self._agent_jobs.get(self.session_id)
        if current_job and current_job.get('done'):
            current_job = None
        self._agent_worker = current_job['worker'] if current_job else None
        self._agent_session_id = self.session_id if current_job else None
        self._agent_operation_id = current_job['operation_id'] if current_job else None
        self._agent_user_text = current_job['user_text'] if current_job else ''
        self._live_agent_text = current_job['live_text'] if current_job else ''
        self.run_id = getattr(self.worker, 'run_id', None)
        self.set_busy(self.worker is not None or current_job is not None)
        self._scope_submitted = False
        self._pending_upload_ids = set()
        self.composer.clear()
        selected = set()
        if self.session_id:
            service = SessionService(self.store)
            try:
                key = (str(service.store.path.resolve()), service.store.owner, self.session_id)
                pending = self._unsaved_drafts.get(key)
                draft = pending[2] if pending is not None else service.draft(self.session_id)
                self.composer.setPlainText(draft['text'])
                selected = set(draft['file_ids'])
                self._scope_submitted = draft['submitted']
                self._draft_binding = (service, self.session_id)
            except (OSError, ValueError, PermissionError, sqlite3.Error):
                self.status.setText('草稿读取失败，未覆盖已保存草稿。请检查项目目录。')
        self.refresh_details(selected_ids=selected)
        self.render_messages()
        if self.session_id:
            if isinstance(self.store, ProjectCatalog):
                self.store.remember_session(self.session_id)
            runs = self.store.runs(self.session_id)
            for run in runs:
                local_store = self.store.active if isinstance(self.store, ProjectCatalog) else self.store
                try:
                    running = self.worker is not None and getattr(self.worker, 'run_id', None) == run['id']
                    recovery = 'running' if running else reconcile_execution(local_store, run['id'])
                    if recovery == 'reconciliation_required':
                        self.status.setText('存在状态待核对的任务；不会自动重跑，请先核对服务端任务状态。')
                except (OSError, ValueError, PermissionError, sqlite3.Error):
                    self.status.setText('任务检查点恢复未完成；未自动重新执行任务。')
                if run["result"]:
                    self.show_result(json.loads(run["result"]), run_id=run["id"])
            self.render_messages()

            try:
                messages = self.store.messages(self.session_id)
                if messages:
                    SessionService(self.store).mark_read(self.session_id, messages[-1]['id'])
            except (OSError, ValueError, PermissionError, sqlite3.Error):
                self.status.setText('已读状态未保存，请检查项目目录；历史消息未删除。')
            self.refresh_session_badges()
            self.session_badge_timer.start()

    def save_current_draft(self, *_args):
        if self._draft_binding is None:
            return
        service, identity = self._draft_binding
        key = (str(service.store.path.resolve()), service.store.owner, identity)
        draft = {'text': self.composer.toPlainText(), 'file_ids': sorted(self.selected_file_ids()),
                 'submitted': getattr(self, '_scope_submitted', False)}
        self._unsaved_drafts[key] = (service, identity, draft)
        try:
            service.save_draft(identity, **draft)
            self._unsaved_drafts.pop(key, None)
        except (OSError, ValueError, PermissionError, sqlite3.Error):
            self.status.setText('草稿未保存（最多12000字、100个附件）；请保留输入并检查项目目录。')

    def flush_unsaved_drafts(self):
        for key, (service, identity, draft) in list(self._unsaved_drafts.items()):
            try:
                service.save_draft(identity, **draft)
                self._unsaved_drafts.pop(key, None)
            except (OSError, ValueError, PermissionError, sqlite3.Error):
                self.status.setText('仍有草稿未保存，暂不能关闭、切换账号或迁移目录；请恢复目录或返回对应会话调整输入。')
                return False
        return True

    def _render_timeline_item(self, item) -> list:
        """把 TimelineItem 渲染成 HTML 片段（S16：渲染只认 ViewModel；
        S10：卡片化层级 + 错误/警告严重级路由）。"""
        from .message_cards import (
            assistant_card_html,
            error_card_html,
            system_event_card_html,
            user_card_html,
            warning_card_html,
        )
        text = html.escape(item.payload.get('text', '')).replace("\n", "<br>")
        raw_text = item.payload.get('text', '')
        if item.kind == 'user':
            return [user_card_html(raw_text)]
        if item.kind == 'live_user':
            return [user_card_html(raw_text, live=True)]
        if item.kind == 'event':
            severity = item.payload.get('severity')
            if severity == 'error':
                return [error_card_html(
                    raw_text,
                    error_code=item.payload.get('error_code', ''),
                    operation_id=item.operation_id or '')]
            if severity == 'warning':
                return [warning_card_html(raw_text)]
            return [system_event_card_html(raw_text)]
        if item.kind == 'assistant':
            return [assistant_card_html(raw_text)]
        if item.kind == 'live_status':
            view = item.payload.get('view')
            if view is not None:
                # S9：实时运行状态卡（真实状态/计时/步骤）
                import dataclasses

                from .run_status import status_card_html
                view = dataclasses.replace(
                    view, text=item.payload.get('text', ''))
                return [status_card_html(view)]
            return [(
                '<p style="font-size:13px;color:#3e4c66"><b>ZQ</b>'
                ' <span style="font-size:10px;color:#a0a6b1"> / ASSISTANT · 生成中</span></p>'
                f'<p style="font-size:14px;line-height:170%;margin-bottom:28px">{text}</p>'
            )]
        if item.kind == 'artifacts':
            return self._run_artifacts_html(item.payload['run'])
        if item.kind == 'legacy_artifacts':
            blocks = ['<p style="color:#758399;font-size:12px">历史成果（旧版本）：</p>']
            for run in item.payload['runs']:
                blocks.extend(self._run_artifacts_html(run))
            return blocks
        return []

    def _run_artifacts_html(self, run) -> list:
        """单个 run 的用户可见成果 HTML（沿用原 render_messages 逐 run 逻辑）。"""
        content = []
        result = json.loads(run['result'] or '{}')
        from .browser_upload_history import upload_history_html
        try:
            content.append(upload_history_html(self.store, run['id']))
        except (ValueError, OSError, sqlite3.Error):
            content.append('<p>上传尝试记录暂不可用；请核对网站状态，不要重复上传。</p>')
        if result.get('kind') == 'browser':
            from .browser_download_delivery import download_links
            try:
                content.append(download_links(self.store, run['id']))
            except (ValueError, OSError, sqlite3.Error):
                content.append('<p>下载成果记录暂不可用，请核对本地项目数据。</p>')
        if result.get('kind') == 'plan' and run['state'] == 'succeeded':
            from .artifact_contract import display_name_of, user_artifacts
            from .plan_results import completed_step_results
            try:
                records = completed_step_results(self.store, self.session_id, run['id'])
                for ordinal, record in enumerate(records):
                    if record['result'].get('kind') == 'review':
                        from .review_delivery import step_review_store
                        scoped = step_review_store(self.store, self.session_id, run['id'], ordinal)
                        review = json.loads(scoped.run(run['id'])['result'])
                        link = f'{run["id"]}/{ordinal}'
                        content.append(f'<p>审核步骤：{html.escape(record["goal"])} '
                            f'<a href="zq-step-export:{link}">生成标准Word审核报告…</a></p>')
                        if review.get('issues'):
                            content.append(f'<p><a href="zq-step-annotate:{link}">生成本步骤问题批注副本…</a>（不修改原件）</p>')
                        for index, path in enumerate(p for batch in review.get('annotations', []) for p in batch['files']):
                            content.append(f'<p>📄 {html.escape(Path(path).name)} '
                                f'<a href="zq-step-comment:{link}/{index}">打开批注副本</a></p>')
                        if review.get('exported_report'):
                            content.append(f'<p>📄 {html.escape(Path(review["exported_report"]).name)} '
                                f'<a href="zq-step-report:{link}">打开审核报告</a></p>')
                    for index, artifact in user_artifacts(record['result']):
                        content.append(f'<p>📄 {html.escape(display_name_of(artifact))}　'
                            f'<a href="zq-step-artifact:{run["id"]}/{ordinal}/{index}">打开步骤成果</a></p>')
            except (ValueError, PermissionError, KeyError, OSError, TypeError):
                content.append('<p>组合成果记录校验失败，请核对任务状态。</p>')
        if result.get('kind') == 'generation':
            try:
                from .artifact_contract import (
                    deliverable_label,
                    display_name_of,
                    user_artifacts,
                )
                visible_artifacts = user_artifacts(result)
            except (ValueError, KeyError, TypeError):
                content.append('<p>生成成果记录校验失败，请核对任务状态。</p>')
                visible_artifacts = []
            if (len(visible_artifacts) == 1 and run['state'] == 'succeeded'
                    and result.get('ok') is True):
                index, artifact = visible_artifacts[0]
                label = deliverable_label(artifact)
                shown = html.escape(display_name_of(artifact))
                if label:
                    content.append(f'<p>{html.escape(label)}已生成并通过校验。</p>')
                content.append(f'<p>最终文件：{shown}　'
                    f'<a href="zq-artifact:{run["id"]}/{index}">打开文件</a>　'
                    f'<a href="zq-artifact-folder:{run["id"]}/{index}">打开所在文件夹</a></p>')
            else:
                for index, artifact in visible_artifacts:
                    shown = html.escape(display_name_of(artifact))
                    content.append(f'<p>📄 {shown}　<a href="zq-artifact:{run["id"]}/{index}">打开文件</a></p>')
        if run['state'] == 'succeeded' and result.get('kind') == 'review':
            identity = run['id']
            content.append(f'<p>审核任务 {html.escape(identity)}：<a href="zq-export:{identity}">生成标准Word审核报告…</a></p>')
            if result.get('issues'):
                content.append(f'<p><a href="zq-annotate:{identity}">生成问题标记和批注副本…</a>（不修改原件）</p>')
            annotation_files = [p for b in result.get('annotations', []) for p in b['files']]
            for index, path in enumerate(annotation_files):
                content.append(f'<p>📄 {html.escape(Path(path).name)} <a href="zq-comment:{identity}/{index}">打开批注副本</a></p>')
            if result.get('exported_report'):
                name = html.escape(Path(result['exported_report']).name)
                content.append(f'<p>📄 {name}　<a href="zq-report:{identity}">打开文件</a>　<a href="zq-folder:{identity}">打开所在文件夹</a></p>')
        return content

    # ------------------------------------------------------- S9 运行状态卡

    @staticmethod
    def _is_foldable_event(item) -> bool:
        """只有中性执行记录参与折叠；错误/警告卡必须始终可见。"""
        return item.kind == 'event' and not item.payload.get('severity')

    def _fold_execution_groups(self, items) -> list:
        """连续 ≥3 条中性执行记录折叠为一组；返回 item 或 (key, events)。"""
        blocks: list = []
        group_keys: list = []
        index = 0
        while index < len(items):
            item = items[index]
            if not self._is_foldable_event(item) or item.message_id is None:
                blocks.append(item)
                index += 1
                continue
            group = [item]
            index += 1
            while (index < len(items)
                   and self._is_foldable_event(items[index])
                   and items[index].message_id is not None):
                group.append(items[index])
                index += 1
            if len(group) >= 3:
                key = f'{self.session_id}:{group[0].message_id}'
                group_keys.append(key)
                blocks.append((key, [g.payload.get('text', '')
                                     for g in group]))
            else:
                blocks.extend(group)
        self._last_event_group_keys = group_keys
        return blocks

    def _expanded_event_groups_snapshot(self) -> list:
        """当前渲染出的折叠组 key 列表（测试与调试入口）。"""
        return list(self._last_event_group_keys)


    def _live_status_view(self, job):
        """从真实 job 记账 + durable operation 推导状态卡视图。"""
        from .run_status import RunStatusView, derive_run_state, derive_step
        now = time.monotonic()
        operation_id = job.get('operation_id') or ''
        operation_status = None
        tools_running = 0
        gateway = job.get('gateway')
        repo = getattr(gateway, 'repo', None)
        if repo is not None and operation_id:
            try:
                record = repo.get_operation(operation_id)
                operation_status = record.status
                tools_running = sum(
                    1 for call in repo.tool_calls(operation_id)
                    if call.status in ('proposed', 'running'))
            except (KeyError, ValueError, sqlite3.Error):
                operation_status = None
        state = derive_run_state(
            'running', operation_status=operation_status,
            stop_requested=bool(job.get('stop_requested')))
        step = derive_step(accepted=bool(operation_id),
                           has_output=bool(job.get('live_text')),
                           tools_running=tools_running)
        return RunStatusView(
            state=state, operation_id=operation_id or 'pending',
            elapsed_seconds=int(now - job.get('started_at', now)),
            last_activity_seconds=int(now - job.get('last_activity_at', now)),
            step_index=step, text='')

    def _terminal_status_line(self):
        """最近一轮的终态摘要行；无终态记录时返回 None。"""
        from .conversation_status import TERMINAL_PHASES
        from .run_status import RunStatusView, terminal_line_html
        status = self.status_controller.turn_phase(self.session_id)
        if status is None or status.phase not in TERMINAL_PHASES - {'waiting'}:
            return None
        elapsed = 0
        if status.started_at and status.last_activity_at:
            elapsed = int(status.last_activity_at - status.started_at)
        view = RunStatusView(
            state=status.phase, operation_id=status.operation_id,
            elapsed_seconds=elapsed, last_activity_seconds=None,
            step_index=3, text='')
        return terminal_line_html(view)

    def _tick_run_status(self) -> None:
        """每秒刷新当前会话状态卡的计时；无活跃任务即停表。"""
        job = self._agent_jobs.get(self.session_id)
        if job is None or job.get('done'):
            self._status_timer.stop()
            return
        self.render_messages()

    def render_messages(self):
        scroll = self.transcript.verticalScrollBar()
        previous_position = scroll.value()
        follow_output = previous_position >= scroll.maximum() - 24
        rows = self.store.messages(self.session_id) if self.session_id else []
        links, runs = [], []
        if self.session_id:
            links = self.store.run_links(self.session_id)
            runs = self.store.runs(self.session_id)
        live = None
        current_job = self._agent_jobs.get(self.session_id)
        if current_job and current_job.get('done'):
            current_job = None
        if current_job is not None:
            live = {'after_message_id': None,
                    'operation_id': current_job['operation_id'],
                    'user_text': current_job['user_text'],
                    'text': current_job['live_text'] or '新 Agent 路径：正在生成…',
                    # S9：实时状态卡视图（真实状态 + 真实计时）
                    'view': self._live_status_view(current_job)}
        agent_entries = []
        if self.session_id:
            try:
                from .sessions.sqlite_repository import SQLiteSessionRepo
                agent_entries = SQLiteSessionRepo(
                    self.store.path, self.store.owner
                ).entries(self.session_id, 'main')
            except (OSError, KeyError, sqlite3.Error):
                # Legacy-only sessions remain renderable during migration.
                agent_entries = []
        from .conversation_timeline import project_timeline

        items = project_timeline(rows, links, runs, live_status=live,
                                 agent_entries=agent_entries)
        content = []
        if self.session_id:
            from .session_service import SessionService
            metadata = next((row for row in SessionService(self.store).list(self.project_id)
                             if row['id'] == self.session_id), None)
            if metadata and metadata['parent_session']:
                content.append(f'<p>分支来源：消息 {int(metadata["fork_message"])} · '
                    f'<a href="zq-parent:{self.session_id}">返回来源会话</a><br>'
                    '分支不继承附件选择、草稿或执行授权。</p>')
                try:
                    references = SessionService(self.store).branch_results(self.session_id)
                    if references:
                        content.append('<p>已完成任务的固定版本引用（不自动执行）：<br>' +
                            '<br>'.join(html.escape(ref['run_id']) for ref in references) + '</p>')
                except (OSError, ValueError, PermissionError, sqlite3.Error):
                    content.append('<p>来源结果已变化或无法校验，未采用该分支引用；请返回来源核对。</p>')
        if self.session_id and not rows and live is None:
            content.append(
                '<p style="color:#858d9b;font-size:14px;line-height:180%">'
                '添加本轮资料，用自然语言描述任务。原始文件只读。</p>')
        for block in self._fold_execution_groups(items):
            if isinstance(block, tuple):
                key, events = block
                from .message_cards import execution_group_html
                content.append(execution_group_html(
                    events, group_id=key,
                    collapsed=key not in self._expanded_event_groups))
            else:
                content.extend(self._render_timeline_item(block))
        if live is None and self.session_id:
            # S9：临时状态卡被终态摘要行替换（内存态，重开会话不残留）
            terminal_html = self._terminal_status_line()
            if terminal_html:
                content.append(terminal_html)
        self.transcript.setHtml(
            "".join(content)
            or (
                '<p style="margin-top:110px;color:#9ca3b2;font-size:12px">ZQ WORKSPACE</p>'
                '<p style="font-size:28px;color:#303745"><b>从一个项目，开始工作。</b></p>'
                '<p style="color:#8d95a3;font-size:14px;line-height:180%">'
                "整理资料，提出问题，让每一步执行都有迹可循。<br>"
                "添加本轮文件，直接描述希望完成的工作。</p>"
                '<p style="margin-top:28px;color:#647087;font-size:12px">'
                "项目上下文　 /　 只读资料预检　 /　 可追溯的执行记录</p>"
            )
        )
        # setHtml 后 QTextDocument 的布局在本轮事件循环末尾才完成；立即 setValue
        # 会读到旧 maximum，导致新消息写入但视图仍停在顶部。延后一拍再定位。
        target = scroll.maximum() if follow_output else previous_position
        QTimer.singleShot(0, lambda: scroll.setValue(scroll.maximum() if follow_output else target))

    def handle_branch_link(self, url):
        from .session_service import SessionService
        try:
            if not self.session_id or url.hasQuery() or url.hasFragment() or url.host():
                raise ValueError('Invalid branch link')
            service = SessionService(self.store)
            if url.scheme() == 'zq-parent':
                if url.path() != self.session_id:
                    raise PermissionError('Stale branch link')
                metadata = next(row for row in service.list(self.project_id) if row['id'] == self.session_id)
                parent = metadata['parent_session']
                if not parent or parent not in {row['id'] for row in service.list(self.project_id)}:
                    raise ValueError('Source session is archived or unavailable')
                self.reload_sessions(parent)
                return
            parts = url.path().split('/')
            if len(parts) != 2 or parts[0] != self.session_id or not parts[1].isascii() or not parts[1].isdigit():
                raise PermissionError('Stale branch link')
            parent, anchor = parts[0], int(parts[1])
            if not any(row['id'] == anchor for row in service.store.messages(parent)):
                raise ValueError('Unknown branch anchor')
            if not self.flush_unsaved_drafts():
                return
            title, accepted = QInputDialog.getText(self, '从消息创建分支',
                                                  '新会话名称（不复制附件或授权）')
            if not accepted:
                return
            if self.session_id != parent:
                raise PermissionError('Conversation changed')
            child = service.fork(parent, anchor, title)
            self.reload_sessions(child)
        except (OSError, ValueError, PermissionError, sqlite3.Error, StopIteration):
            self.status.setText('分支操作未完成：请确认消息属于当前会话、名称有效且来源会话未归档。')

    def handle_report_link(self, url):
        from .report_export import export_review
        action = url.scheme()
        if action == 'zq-events':
            # S10：执行记录折叠组展开/收起（仅允许当前渲染出的组 key）
            key = url.path()
            if not key or url.hasQuery() or url.hasFragment() or url.host():
                return
            if key not in self._last_event_group_keys:
                return
            if key in self._expanded_event_groups:
                self._expanded_event_groups.discard(key)
            else:
                self._expanded_event_groups.add(key)
            self.render_messages()
            return
        if action == 'zq-diagnostics':
            # S10：复制诊断信息——只含公开字段，不含 traceback/凭据
            if url.hasQuery() or url.hasFragment() or url.host():
                return
            parts = url.path().split('/')
            operation_id = parts[0] if parts and parts[0] else ''
            if not operation_id:
                return
            error_code = parts[1] if len(parts) > 1 else ''
            summary = ''
            status = self.status_controller.turn_phase(
                self.session_id, operation_id)
            if status is not None:
                summary = status.text
            from PySide6.QtGui import QGuiApplication

            from .message_cards import diagnostics_text
            QGuiApplication.clipboard().setText(diagnostics_text(
                operation_id=operation_id, error_code=error_code,
                summary=summary, client_version=CLIENT_VERSION))
            return
        if action == 'zq-download-folder':
            from .browser_download_delivery import download_folder
            try:
                if not self.session_id or url.hasQuery() or url.hasFragment() or url.host():
                    raise ValueError('Invalid download link')
                run_id, identity = url.path().split('/')
                folder = download_folder(self.store, self.session_id, run_id, identity)
                if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder))):
                    raise OSError('Unable to open folder')
            except (ValueError, OSError, sqlite3.Error, KeyError):
                self.status.setText('下载入口不可用：文件可能已移动或变化，请核对原下载目录。')
            return
        if action in {'zq-branch', 'zq-parent'}:
            self.handle_branch_link(url)
            return
        if action in {'zq-step-annotate', 'zq-step-comment'}:
            try:
                from .review_delivery import step_review_store
                parts = url.path().split('/')
                expected = 2 if action == 'zq-step-annotate' else 3
                if len(parts) != expected:
                    raise ValueError('无效步骤链接')
                run_id, ordinal = parts[:2]
                task_store = self.store.active if isinstance(self.store, ProjectCatalog) else self.store
                scoped = step_review_store(task_store, self.session_id, run_id, int(ordinal))
                if action == 'zq-step-annotate':
                    self.offer_annotations(run_id, explicit=True, step_index=int(ordinal))
                else:
                    result = json.loads(scoped.run(run_id)['result'])
                    paths = [p for batch in result.get('annotations', []) for p in batch['files']]
                    index = int(parts[2])
                    if not 0 <= index < len(paths):
                        raise ValueError('无效批注文件编号')
                    path = Path(paths[index])
                    if not path.is_file() or not QDesktopServices.openUrl(QUrl.fromLocalFile(str(path))):
                        raise ValueError('批注副本已移动或无法打开')
            except (ValueError, PermissionError, KeyError, OSError) as exc:
                QMessageBox.warning(self, '步骤批注', str(exc))
            return
        if action in {'zq-step-export', 'zq-step-report'}:
            try:
                from .project_catalog import validate_business_directory
                from .review_delivery import step_review_store
                run_id, ordinal = url.path().split('/')
                task_store = self.store.active if isinstance(self.store, ProjectCatalog) else self.store
                scoped = step_review_store(task_store, self.session_id, run_id, int(ordinal))
                if action == 'zq-step-export':
                    default_path = task_store.path.parent / f'审核记录-{int(ordinal) + 1}.docx'
                    selected, _ = QFileDialog.getSaveFileName(self, '保存步骤审核报告', str(default_path), 'Word 文档 (*.docx)')
                    if not selected:
                        return
                    validate_business_directory(Path(selected).parent)
                    export_review(scoped, run_id, Path(selected))
                    self.render_messages()
                    self.status.setText('本步骤标准审核报告已生成，原文件未修改。')
                else:
                    path = Path(json.loads(scoped.run(run_id)['result'])['exported_report'])
                    if not path.is_file() or not QDesktopServices.openUrl(QUrl.fromLocalFile(str(path))):
                        raise ValueError('报告已移动或无法打开，请重新导出或检查默认应用。')
            except (ValueError, PermissionError, KeyError, OSError) as exc:
                QMessageBox.warning(self, '步骤审核报告', str(exc))
            return
        if action == 'zq-step-artifact':
            try:
                from .plan_results import step_artifact_path
                run_id, step_index, index = url.path().split('/')
                path = step_artifact_path(self.store, self.session_id, run_id, int(step_index), int(index))
                if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(path))):
                    raise ValueError('无法打开文件，请检查默认应用')
            except (ValueError, PermissionError, KeyError, OSError) as exc:
                QMessageBox.warning(self, '步骤成果', str(exc))
            return
        if action == 'zq-comment':
            try:
                identity, index = url.path().split('/')
                run = self.store.run(identity)
                if run['session'] != self.session_id:
                    return
                result = json.loads(run['result'])
                paths = [p for b in result.get('annotations', []) for p in b['files']]
                path = Path(paths[int(index)])
                if not path.is_file():
                    raise ValueError('批注文件已移动或删除，请重新生成。')
                QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
            except (ValueError, OSError, IndexError, KeyError) as exc:
                QMessageBox.warning(self, '批注副本', str(exc))
            return
        if action == 'zq-annotate':
            self.offer_annotations(url.path(), explicit=True)
            return
        if action in {'zq-artifact', 'zq-artifact-folder'}:
            try:
                from .generation import artifact_path
                run_id, index = url.path().split('/')
                path = artifact_path(self.store, self.session_id, run_id, int(index))
                target = path.parent if action == 'zq-artifact-folder' else path
                if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(target))):
                    raise ValueError('无法打开文件，请检查默认应用')
            except (ValueError, OSError, KeyError, PermissionError) as exc:
                QMessageBox.warning(self, '生成成果', str(exc))
            return
        if action not in {'zq-export', 'zq-report', 'zq-folder'}:
            return
        try:
            run_id = url.path()
            run = self.store.run(run_id)
            if run['session'] != self.session_id:
                return
            if action == 'zq-export':
                output_root = self.store.path.parent
                if output_root.name == ".zq":
                    output_root = output_root.parent
                default_path = str(output_root / '审核记录.docx')
                path, _ = QFileDialog.getSaveFileName(self, '保存标准审核报告', default_path, 'Word 文档 (*.docx)')
                if not path:
                    return
                if isinstance(self.store, ProjectCatalog):
                    from .project_catalog import validate_business_directory

                    validate_business_directory(Path(path).parent)
                export_review(self.store, run_id, Path(path))
                self.render_messages()
                self.status.setText('标准审核报告已生成，未修改送审原文件。')
            else:
                path = Path(json.loads(run['result'])['exported_report'])
                if not path.is_file():
                    raise ValueError('报告文件已移动或删除，请重新导出。')
                if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.parent if action == 'zq-folder' else path))):
                    raise ValueError('无法打开文件，请检查默认应用设置。')
        except (ValueError, OSError, KeyError) as exc:
            QMessageBox.warning(self, '报告导出', str(exc))

    def selected_file_ids(self):
        return {
            self.files.item(i).data(Qt.ItemDataRole.UserRole)
            for i in range(self.files.count())
            if self.files.item(i).checkState() == Qt.CheckState.Checked
        }

    def scope_summary_text(self):
        if self.last_turn_envelope is None:
            return ''
        from .turn_scope_policy import format_scope_summary
        return format_scope_summary(self.last_turn_envelope)

    def refresh_details(self, selected_ids=None):
        blocker = QSignalBlocker(self.files)
        if selected_ids is None:
            selected_ids = self.selected_file_ids()
        self.files.clear()
        self.memories.clear()
        if not self.project_id:
            self._file_rows = []
            self._file_records = {}
            self._artifact_entries = []
            self._task_records = []
            self.artifacts_list.clear()
            self.tasks_list.clear()
            self.task_detail.setText("双击任务查看详情")
            self.project_summary.setVisible(False)
            return
        files = self.store.files(self.project_id)
        self._file_records = {item['id']: item for item in files}
        self._file_rows = build_file_rows(
            files, selected_ids=set(selected_ids),
            used_ids=self._used_file_ids())
        for view in self._file_rows:
            row = QListWidgetItem(row_label(view, files_map={}))
            row.setData(Qt.ItemDataRole.UserRole, view.file_id)
            row.setFlags(row.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            row.setCheckState(
                Qt.CheckState.Checked
                if view.selected
                else Qt.CheckState.Unchecked
            )
            self.files.addItem(row)
        from .memory_service import MemoryService
        from .ui.memory_panel import memory_label
        records = (MemoryService(self.store).list_for_context(self.session_id)
                   if self.session_id else [])
        for item in records:
            row = QListWidgetItem(memory_label(item))
            row.setData(Qt.ItemDataRole.UserRole, item.id)
            if item.status == "revoked":
                row.setFlags(row.flags() & ~Qt.ItemFlag.ItemIsEnabled)
            self.memories.addItem(row)
        del blocker
        self._apply_file_filter()
        self._refresh_artifacts_and_tasks()
        self._update_project_summary()
        self.save_current_draft()

    def _update_project_summary(self):
        """动态项目摘要：真实统计文件/会话/成果数量。"""
        if not self.project_id:
            self.project_summary.setVisible(False)
            return
        files = len(self.store.files(self.project_id))
        sessions = len(self.store.sessions(self.project_id))
        artifacts = len(self._artifact_entries)
        self.project_summary.setText(
            f'{files} 个文件 · {sessions} 个会话 · {artifacts} 项成果')
        self.project_summary.setVisible(True)

    def _refresh_artifacts_and_tasks(self):
        """成果 Tab 与任务 Tab：数据全部来自 store 真实 runs 记录。"""
        self._artifact_entries = collect_artifacts(self.store, self.project_id)
        self.artifacts_list.clear()
        for index, entry in enumerate(self._artifact_entries):
            row = QListWidgetItem(artifact_row_text(entry))
            row.setData(Qt.ItemDataRole.UserRole, index)
            self.artifacts_list.addItem(row)
        self._task_records = []
        self.tasks_list.clear()
        for session in self.store.sessions(self.project_id):
            for run in self.store.runs(session['id']):
                try:
                    snapshot = json.loads(run.get('snapshot') or '{}')
                except (TypeError, ValueError):
                    snapshot = {}
                self._task_records.append((run, snapshot))
                row = QListWidgetItem(task_row_text(run, snapshot))
                row.setData(Qt.ItemDataRole.UserRole,
                            len(self._task_records) - 1)
                self.tasks_list.addItem(row)

    def _selected_artifact_entry(self):
        row = self.artifacts_list.currentRow()
        if row < 0 and self.artifacts_list.count():
            row = 0
        if not 0 <= row < len(self._artifact_entries):
            return None
        return self._artifact_entries[row]

    def _resolve_artifact_path(self, entry):
        """generation 成果走带范围校验的 artifact_path；其余校验文件存在。"""
        if entry.kind == 'generation' and entry.index is not None:
            from .generation import artifact_path
            return artifact_path(self.store, entry.session_id,
                                 entry.run_id, entry.index)
        path = Path(entry.path)
        if not path.is_file():
            raise ValueError('成果文件已移动或删除，请在项目目录核对。')
        return path

    def open_selected_artifact(self):
        entry = self._selected_artifact_entry()
        if entry is None:
            return
        try:
            path = self._resolve_artifact_path(entry)
            if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(path))):
                raise ValueError('无法打开文件，请检查默认应用')
        except (ValueError, OSError, PermissionError) as exc:
            QMessageBox.warning(self, '成果', str(exc))

    def save_artifact_as(self):
        entry = self._selected_artifact_entry()
        if entry is None:
            return
        try:
            source = self._resolve_artifact_path(entry)
        except (ValueError, OSError, PermissionError) as exc:
            QMessageBox.warning(self, '成果', str(exc))
            return
        target, _ = QFileDialog.getSaveFileName(self, '另存为', entry.name)
        if not target:
            return
        destination = Path(target)
        staging = destination.with_name(destination.name + '.part')
        try:
            shutil.copy2(source, staging)
            os.replace(staging, destination)
        except OSError as exc:
            try:
                staging.unlink(missing_ok=True)
            except OSError:
                staging = None
            QMessageBox.warning(self, '成果', f'另存为失败：{exc}')
            return
        self.status.setText(f'成果已另存为：{destination.name}')

    def show_task_detail(self, item):
        index = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(index, int) or not 0 <= index < len(self._task_records):
            return
        run, snapshot = self._task_records[index]
        try:
            result = json.loads(run.get('result') or '{}')
        except (TypeError, ValueError):
            result = {}
        self.task_detail.setText(task_detail_text(run, snapshot, result))

    def _used_file_ids(self):
        """历史任务快照中真实使用过的文件 id 集合。"""
        used = set()
        if not self.project_id:
            return used
        for session in self.store.sessions(self.project_id):
            for run in self.store.runs(session['id']):
                try:
                    snapshot = json.loads(run.get('snapshot') or '{}')
                except (TypeError, ValueError):
                    continue
                for entry in snapshot.get('selected_files') or []:
                    file_id = entry.get('id') if isinstance(entry, dict) else None
                    if file_id:
                        used.add(file_id)
        return used

    _FILE_FILTER_KINDS: ClassVar = {
        '全部文件': 'all',
        '本轮已选': 'selected',
        '未使用': 'unused',
        '已用于任务': 'used',
    }

    def _apply_file_filter(self, *_args):
        kind = self._FILE_FILTER_KINDS.get(self.file_filter.currentText(), 'all')
        visible = {
            row.file_id
            for row in filter_rows(self._file_rows, self.file_search.text(), kind)
        }
        for i in range(self.files.count()):
            item = self.files.item(i)
            item.setHidden(item.data(Qt.ItemDataRole.UserRole) not in visible)

    def _set_visible_check_state(self, state):
        blocker = QSignalBlocker(self.files)
        for i in range(self.files.count()):
            item = self.files.item(i)
            if not item.isHidden():
                item.setCheckState(state)
        del blocker
        self.save_current_draft()

    def select_visible_files(self):
        self._set_visible_check_state(Qt.CheckState.Checked)

    def clear_visible_files(self):
        self._set_visible_check_state(Qt.CheckState.Unchecked)

    def show_file_detail(self, item):
        file_id = item.data(Qt.ItemDataRole.UserRole)
        record = self._file_records.get(file_id)
        view = next((r for r in self._file_rows if r.file_id == file_id), None)
        if record is None or view is None:
            return
        self.file_detail.setText(file_detail_text(
            view, sha256=record['sha256'], path=record.get('path', '')))

    def add_files(self):
        if not self.project_id or not self.attach.isEnabled():
            return
        paths, _ = QFileDialog.getOpenFileNames(
            self, "添加项目资料", "", "资料 (*.docx *.xlsx *.xls *.xlsm *.pdf *.json *.zip)"
        )
        self.import_files(paths)

    def eventFilter(self, watched, event):
        if event.type() in (
            QEvent.Type.DragEnter, QEvent.Type.DragMove, QEvent.Type.Drop
        ) and event.mimeData().hasUrls():
            if not self.project_id or not self.attach.isEnabled():
                self.status.setText("请先打开项目，并等待当前任务结束后添加文件。")
                event.ignore()
                return True
            event.setDropAction(Qt.DropAction.CopyAction)
            event.accept()
            if event.type() == QEvent.Type.Drop:
                urls = event.mimeData().urls()
                self.import_files([url.toLocalFile() for url in urls if url.isLocalFile()])
                if any(not url.isLocalFile() for url in urls):
                    self.status.setText(self.status.text() + "；已拒绝非本地文件链接。")
            return True
        return super().eventFilter(watched, event)

    def import_files(self, paths):
        if not self.project_id or not self.attach.isEnabled():
            return
        existing = self.store.files(self.project_id)
        known = {(f["name"], f["sha256"]): f['id'] for f in existing}
        selected = set() if getattr(self, '_scope_submitted', False) else self.selected_file_ids()
        imported = {}
        added = skipped = 0
        errors = []
        for raw in paths:
            try:
                path = Path(raw).resolve()
                if path.is_dir():
                    errors.append(f"{path.name}：不支持文件夹")
                    continue
                if path.suffix.lower() not in {".docx", ".xlsx", ".xls", ".xlsm", ".pdf", ".json", ".zip"}:
                    errors.append(f"{path.name}：不支持的文件类型")
                    continue
                hashed = digest(path)
                if (path.name, hashed) not in known:
                    identity = self.store.add_file(self.project_id, path, hashed)
                    known[(path.name, hashed)] = identity
                    added += 1
                else:
                    skipped += 1
                imported[path.name] = known[(path.name, hashed)]
            except OSError:
                errors.append(f"{Path(raw).name}：文件无法读取或复制")
        if imported:
            selected -= {f['id'] for f in existing if f['name'] in imported}
            selected.update(imported.values())
            pending = getattr(self, '_pending_upload_ids', set())
            pending.update(imported.values())  # 本轮上传必须进入上下文，与勾选无关
            self._pending_upload_ids = pending
            self._scope_submitted = False
            self.refresh_details(selected_ids=selected)
            self.details.show()
            self.details.setCurrentIndex(0)
        message = (f"已添加 {added} 个文件，复用 {skipped} 个重复文件。"
                   f"本轮选中 {len(self.selected_file_ids())} 个文件；"
                   "本轮上传的文件会自动带入上下文，历史资料可由 Agent 按需读取。")
        if errors:
            message += "\n" + "；".join(errors)
        self.status.setText(message)

    def try_resume_waiting_run(self, prompt):
        """Resume a generation run paused for material clarification.

        The reply is matched deterministically against the persisted
        candidates; a successful match resumes from the disambiguation node
        without any new model call, while a mismatch re-asks the question.
        """
        store = self.store.active if isinstance(self.store, ProjectCatalog) else self.store
        if store is None or self.session_id is None:
            return False
        waiting = next((r for r in reversed(store.runs(self.session_id))
                        if r['state'] == 'waiting_user'), None)
        if waiting is None:
            return False
        run_id = waiting['id']
        try:
            result = json.loads(waiting['result'] or '{}')
        except ValueError:
            result = {}
        pending = result.get('pending')
        if not isinstance(pending, dict):
            return False
        if any(word in prompt for word in ('取消', '放弃')):
            store.transition(run_id, 'cancelled', '用户在澄清阶段取消任务')
            store.append(self.session_id, 'assistant', '已取消等待澄清的任务；没有生成文件。')
            self.status.setText('任务已取消。')
            self.render_messages()
            return True
        from .material_resume import match_clarification
        override = match_clarification(pending, store.files(store.session(self.session_id)['project']),
                                       prompt)
        if override is None:
            questions = '；'.join(result.get('questions') or [])
            store.append(self.session_id, 'assistant',
                         '仍无法唯一确定本轮主体或期间，请回复明确的主体名称、期间或文件名。' + questions)
            self.status.setText('等待补充信息：请明确主体、期间或文件名。')
            self.render_messages()
            return True
        try:
            store.set_material_resolution_override(run_id, override)
        except (ValueError, PermissionError) as exc:
            store.append(self.session_id, 'assistant', f'澄清未能应用：{exc}')
            self.status.setText('澄清未能应用，请重新提交任务。')
            self.render_messages()
            return True
        provider = None
        snapshot = json.loads(store.run(run_id)['snapshot'])
        if snapshot.get('automatic_materials') is True:
            if self.client is None:
                self.status.setText('请先连接服务端，才能继续已澄清的任务')
                return True
            from .generation import bundle_fingerprint
            from .material_analysis import MaterialAnalysisProvider
            provider = MaterialAnalysisProvider(
                self.client, snapshot.get('model') or self.model_combo.currentData(),
                bundle_fingerprint(snapshot['skill_id']))
        store.append(self.session_id, 'event',
                     '已按澄清恢复任务；沿用已完成的识别结果，不重复调用模型。')
        self.composer.clear()
        self.render_messages()
        worker = self.register_task_worker(TaskWorker(store, run_id, self, provider=provider))
        self.set_busy(True)
        worker.start()
        return True

    def submit(self):
        if not self.session_id or self.worker or self._agent_worker is not None:
            return
        prompt = self.composer.toPlainText().strip()
        if not prompt:
            return
        if self.try_local_skill_install(prompt):
            return
        gateway_factory = getattr(self._make_agent_gateway, '__func__', None)
        injected_gateway = gateway_factory is not PlatformWindow._make_agent_gateway
        from .input_gateway import InputGateway
        try:
            envelope = InputGateway(
                self.store,
                self.agent_permission_mode,
            ).create(
                self.session_id,
                prompt,
                selected_ids=self.selected_file_ids(),
                model_id=self.model_combo.currentData(),
                newly_attached_ids=tuple(getattr(self, '_pending_upload_ids', set())),
            )
            InputGateway(self.store, self.agent_permission_mode).verify(envelope)
            self.last_turn_envelope = envelope
        except (ValueError, PermissionError, KeyError, sqlite3.Error) as exc:
            self.composer.setPlainText(prompt)
            self.status.setText(str(exc))
            return
        if not injected_gateway and self.try_local_builtin(prompt):
            return
        if self.client is None:
            connector = getattr(self, 'connect_service', None)
            connector_factory = getattr(connector, '__func__', None)
            injected_connector = connector_factory is not PlatformWindow.connect_service
            if (not injected_gateway and injected_connector and callable(connector)
                    and connector() is False):
                self.composer.setPlainText(prompt)
                self.status.setText('当前未连接服务端，本轮未发送；可连接后重试。')
                return
        # Test/offline adapters intentionally expose the stage-1 contract but
        # do not carry a RemoteSessionClient access token.  Keep that narrow
        # adapter path usable for local previews and deterministic Qt tests;
        # authenticated production clients remain new-Agent-only below.
        if self._can_use_stage1_compat_client():
            # The compatibility adapter still performs a model/network call.
            # It must therefore pass the same permission gate as the new Agent
            # path; otherwise request mode would clear the composer and start
            # work even after the user rejected approval.
            if not self.agent_operation_allowed(
                'network', '确认 Agent 执行',
                f'确认允许 Agent 按本轮选中的 {len(self.selected_file_ids())} 个文件和用户要求执行？',
            ):
                self.composer.setPlainText(prompt)
                self.status.setText('已取消执行，未启动任务。')
                return
            self._submit_stage1_compat(prompt)
            return
        # 正式客户端只允许新 Agent；旧 TurnRouter 链路不再作为回退入口。
        # 本轮上传的文件必须进上下文（与勾选无关）；其余勾选文件按显式选择
        # 随消息一起冻结进 operation 绑定，模型才看得到文件。
        checked = self.selected_file_ids()
        uploads = set(getattr(self, '_pending_upload_ids', set()))
        self._try_agent_submit(prompt, file_ids=sorted(checked - uploads),
                               upload_ids=sorted(uploads))
        return

    def _can_use_stage1_compat_client(self):
        client = self.client
        from ..report_review_app.services.remote_auth_service import RemoteSessionClient
        return (client is not None
                and callable(getattr(client, 'understand_task', None))
                and (not getattr(client, 'access_token', None)
                     or not isinstance(client, RemoteSessionClient)))

    def _submit_stage1_compat(self, prompt):
        """Run the pre-Agent stage-1 contract for local/test adapters only.

        This is deliberately capability-based rather than environment/test
        name based.  A real logged-in client always has an access token and is
        therefore handled exclusively by ``_try_agent_submit``.
        """
        from .routing import ConsultWorker
        selected = self.selected_file_ids()
        candidates = self._installed_skill_candidates()
        worker = ConsultWorker(
            self.client, self.store, self.session_id, prompt,
            model_id=self.model_combo.currentData() or '',
            selected_ids=selected,
            candidates=candidates,
            browser_enabled=True,
            parent=self,
        )
        self.register_consult_worker(worker)
        self.composer.clear()
        self.set_busy(True)
        self.status.setText('Agent 正在理解本轮要求…')
        self.render_messages()
        worker.start()

    def _installed_skill_candidates(self):
        """Return enabled data-only Skill identities for stage-1 routing."""
        from .skill_installation import SkillInstallation

        try:
            manager = SkillInstallation(self.store, initialize=False)
            result = []
            for row in manager.list_versions():
                if not row['enabled']:
                    continue
                package = manager.load(row['skill_id'], row['version'])
                if not package.ready:
                    continue
                manifest = package.manifest
                result.append({
                    'id': manifest['id'],
                    'name': manifest['name'],
                    'adapter': manifest['adapter'],
                    'description': str(manifest.get('description', ''))[:1000],
                })
            return result
        except (OSError, ValueError, PermissionError, sqlite3.Error, KeyError, TypeError):
            return []

    def try_local_builtin(self, prompt: str) -> bool:
        """Route new local-only built-ins without requiring a cloud schema change."""
        from .skills import DETAIL, FINANCIAL_BRIEF, HISTORY, WORKFLOW_TO_SKILL

        normalized = ''.join(prompt.casefold().split())
        financial = any(token in normalized for token in
                        ('财务简报', '财务状况简表', 'financialbrief'))
        detail = any(token in normalized for token in
                     ('评估明细表', 'valuationdetailworkbook', '明细工作簿'))
        workflow = (('skill' in normalized or '技能' in normalized)
                    and '工作流' in normalized
                    and any(token in normalized for token in ('创建', '制作', '生成', '更新', '校验')))
        if not financial and not detail and not workflow:
            return False
        chain = []
        if detail:
            chain.append(self.registry.get(DETAIL.id))
        if financial:
            if '历史沿革' in normalized or '工商沿革' in normalized:
                chain.append(self.registry.get(HISTORY.id))
            chain.append(self.registry.get(FINANCIAL_BRIEF.id))
        elif not detail:
            chain.append(self.registry.get(WORKFLOW_TO_SKILL.id))
        files = [item for item in self.store.files(self.project_id)
                 if item['id'] in self.selected_file_ids()]
        if len(chain) > 1:
            self.store.append(self.session_id, 'event',
                              '本轮将依次执行：' + ' → '.join(spec.name for spec in chain))
        previous_run = self.run_id
        self.execute_plan(prompt, chain[0], selected_files=files or None)
        if len(chain) > 1 and self.run_id != previous_run:
            self._local_chain = {'prompt': prompt, 'files': files,
                                 'specs': chain[1:], 'run': self.run_id}
        else:
            self._local_chain = None
        return True

    def try_local_skill_install(self, prompt: str) -> bool:
        """Handle an explicit current-turn data-only Skill install without a model call."""
        normalized = ''.join(prompt.casefold().split())
        if not (('skill' in normalized or '技能' in normalized)
                and any(word in normalized for word in ('安装', 'install', '加入平台', '注册'))):
            return False
        selected = self.selected_file_ids()
        files = [item for item in self.store.files(self.project_id) if item['id'] in selected]
        packages = [item for item in files if Path(item['name']).suffix.lower() == '.zip']
        if len(packages) != 1 or len(files) != 1:
            self.status.setText('安装 Skill 需要本轮只选择一个 ZIP 包；历史附件不会自动采用。')
            return True
        from .skill_installation import SkillInstallation
        from .skill_manager import SkillManagerDialog
        from .skill_package import inspect_package
        try:
            package = inspect_package(Path(packages[0]['path']))
            summary = SkillManagerDialog.describe(package)
            if not self.agent_operation_allowed(
                'install_skill', '确认安装并启用 Skill',
                summary + '\n\n确认安装、注册并启用此版本？',
            ):
                self.status.setText('已取消安装；没有写入 Skill 注册表。')
                return True
            manager = SkillInstallation(self.store)
            manager.install(Path(packages[0]['path']), confirmed=True,
                            expected_sha256=package.sha256)
            manager.activate(package.manifest['id'], package.manifest['version'], confirmed=True)
            self.store.append(self.session_id, 'user', prompt)
            self.store.append(self.session_id, 'assistant',
                              f"已安装并启用 {package.manifest['name']} {package.manifest['version']}。"
                              '后续由 Agent 根据自然语言自动选择；未执行包内脚本，也未授予修改原件权限。')
            self._scope_submitted = True
            self.composer.clear()
            self.refresh_details(selected_ids=set())
            self.render_messages()
            self.status.setText('Skill 已完成完整性检查、安装、注册和启用。')
        except (ValueError, PermissionError, OSError) as exc:
            self.status.setText(str(exc))
        return True

    def routing_finished(self, worker, destination):
        if not self.release_worker(worker, destination):
            return
        plan, pending, error = worker.plan, worker.pending, worker.error
        cancelled = worker.cancel.is_set()
        worker.deleteLater()
        if error or cancelled:
            try:
                worker.controller.cancel(pending)
                worker.controller.store.append(pending.session_id, 'assistant', error or '任务理解已取消。')
            except (ValueError, PermissionError):
                pass
            if destination.visible(self):
                self.status.setText(error or '任务理解已取消。')
                self.render_messages()
            return
        try:
            understanding = worker.controller.complete(pending, plan)
        except ClarificationContextLimit as exc:
            worker.controller.store.append(pending.session_id, 'assistant', str(exc))
            if destination.visible(self):
                self.status.setText(str(exc))
                self.render_messages()
            return
        except (ValueError, PermissionError):
            if destination.visible(self):
                self.status.setText('理解结果或文件范围已失效，请重新提交；未执行业务。')
                self.render_messages()
            return
        if not destination.visible(self):
            if understanding.next_action in {'plan', 'browser'}:
                destination.store.append(pending.session_id, 'assistant',
                    '任务理解已完成；当前已切换会话，未自动执行。请返回本会话确认后重新发起。')
            return
        self.render_messages()
        if understanding.next_action == 'browser':
            from .browser_window import start_browser_task
            start_browser_task(self, pending, understanding)
            return
        if understanding.next_action != 'plan':
            self.status.setText('等待补充信息' if understanding.next_action == 'ask' else '已回复')
            return
        if (self.store.owner != pending.owner or self.session_id != pending.session_id
                or self.project_id != pending.project_id):
            self.status.setText('理解结果已保存在原会话；当前会话已变化，未自动执行。')
            return
        if len(understanding.skill_ids) != 1 or understanding.references:
            self.execute_compound(pending, understanding, worker.proposal)
            return
        files = [f for f in pending.files if f['id'] in understanding.targets]
        skill_id = understanding.skill_ids[0]
        package = worker.routing_packages.get(skill_id)
        spec = self.registry.get(package.manifest['adapter'] if package else skill_id)
        prompt = pending.request.prompt
        if pending.request.context:
            prompt = ('本轮用户对话：\n' + '\n'.join(
                m.text for m in pending.request.context if m.role == 'user') + '\n' + prompt)
        self.execute_plan(prompt, spec, package=package, selected_files=files, record_user=False)

    def consult_finished(self, worker, destination):
        if not self.release_worker(worker, destination):
            return
        outcome, error = worker.outcome, worker.error
        prompt = worker.prompt
        worker.deleteLater()
        if error or outcome is None:
            # The router persisted nothing on this path; restore the prompt so no
            # user input is lost and nothing half-written pollutes the session.
            if destination.visible(self):
                self.composer.setPlainText(prompt)
                self.status.setText(error or '本轮消息已取消。')
            return
        if outcome.kind == 'execution':
            if not destination.visible(self):
                from .agent_controller import AgentController
                try:
                    AgentController(destination.store).cancel(outcome.pending)
                    destination.store.append(worker.session_id, 'assistant',
                        '任务理解已取消；当前已切换会话，未自动执行。请返回本会话重新发起。')
                except (ValueError, PermissionError):
                    pass
                return
            from .agent_controller import AgentController
            from .routing import UnderstandingWorker
            controller = AgentController(self.store)
            understanding = UnderstandingWorker(self.client, outcome.pending, self)
            understanding.controller = controller
            self.register_understanding_worker(understanding)
            self.render_messages()
            self.set_busy(True)
            self.status.setText('Agent 正在理解本轮要求并选择执行能力…')
            understanding.start()
            return
        if destination.visible(self):
            self.status.setText('已回复')
            self.render_messages()

    def confirm_compound_plan(self, snapshot):
        from .agent_permission_modes import (
            requires_browser_confirmation,
            requires_confirmation,
        )

        mode = self.agent_permission_mode()
        if snapshot.get('mode') == 'browser_task':
            actions = snapshot.get('browser_scope', {}).get('actions', [])
            if not any(requires_browser_confirmation(mode, action) for action in actions):
                return True
        elif not requires_confirmation(
            mode, 'network' if snapshot.get('permissions', {}).get('call_model') else 'generate_file'
        ):
            return True
        from .plan_confirmation import PlanConfirmationDialog
        return PlanConfirmationDialog(snapshot, self.store.path.parent, self).exec() == QDialog.DialogCode.Accepted

    def execute_compound(self, pending, understanding, proposal):
        from .compound_task import build_compound_task_spec
        from .conversation_state import ConversationState
        from .permissions import PermissionService
        task_store = self.store.active if isinstance(self.store, ProjectCatalog) else self.store
        created_run = None
        def current():
            if (self.session_id != pending.session_id or self.project_id != pending.project_id
                    or self.store.owner != pending.owner or self.model_combo.currentData() != pending.request.model_id):
                return False
            state = ConversationState(task_store).read(pending.session_id)
            # AgentController.complete closes this understanding revision once.
            return (state['task_id'] == pending.task_id and state['revision'] == pending.revision + 1
                    and state['cancelled'])
        try:
            if self.worker or task_store is None or not current():
                raise ValueError('模型或任务状态已变化，请重新提交')
            snapshot = build_compound_task_spec(task_store, pending.session_id,
                {'request': pending.request.model_dump(), 'understanding': understanding.model_dump()},
                proposal, list(pending.files), revision=pending.revision).to_snapshot()
            snapshot['permission_mode'] = self.agent_permission_mode()
            if not self.confirm_compound_plan(snapshot):
                self.status.setText('已取消计划，未启动业务步骤。')
                return
            if not current():
                raise ValueError('确认期间项目、会话或模型已变化，请重新提交')
            created_run = task_store.start_run(pending.session_id, snapshot)
            PermissionService(task_store).authorize(created_run, snapshot, confirmed=True)
        except (ValueError, PermissionError, OSError, sqlite3.Error):
            if created_run is not None:
                task_store.transition(created_run, 'failed', 'authorization: confirmation persistence failed')
            self.status.setText('计划或授权校验未通过，未启动业务步骤。')
            return
        self.run_id = created_run
        self._scope_submitted = True
        self.save_current_draft()
        self.store.append(pending.session_id, 'event', '已确认组合计划：\n' + '\n'.join(
            f"{index}. {step['goal']}" for index, step in enumerate(snapshot['execution_plan']['steps'], 1)))
        worker = self.register_task_worker(TaskWorker(task_store, self.run_id, self, client=self.client))
        self.render_messages()
        self.set_busy(True)
        worker.start()

    def execute_plan(self, prompt, spec, *, package=None, selected_files=None, record_user=True):
        if not self.session_id or self.worker:
            return
        if record_user:
            self.store.append(self.session_id, "user", prompt)
        self.composer.clear()
        files = selected_files
        if files is None:
            selected_ids = self.selected_file_ids()
            files = [item for item in self.store.files(self.project_id) if item['id'] in selected_ids]
        if not files:
            self.store.append(
                self.session_id, "assistant", "请先添加资料，再执行只读预检。"
            )
            self.render_messages()
            return
        selected_name = package.manifest['name'] if package else spec.name
        note = ('文件范围及写入权限仍需独立校验。'
                if spec not in GENERATORS or self.generation_consent_required()
                else '已按当前权限模式直接执行；只生成副本，不修改原件。')
        self.store.append(self.session_id, 'event', f'Agent 选择：{selected_name}。{note}')
        if spec.id == REVIEW.id:
            names = '\n'.join(f"• {item['name']}" for item in files)
            answer = QMessageBox.question(
                self, '确认本轮送审范围',
                f'本轮只读取以下 {len(files)} 个文件：\n{names}\n\n'
                '请确认与本轮要求一致。若不一致，请取消后在文件列表调整勾选。'
                '\n历史对话不会自动增加送审文件。',
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel,
            )
            if answer != QMessageBox.StandardButton.Yes:
                self.composer.setPlainText(prompt)
                self.render_messages()
                return
        generation_roles = None
        generation_confirmed = False
        if spec in GENERATORS:
            from .generation import locked_template
            try:
                if spec.id != 'office-workflow-to-skill':
                    locked_template(spec.id)
            except (ValueError, OSError, PermissionError) as exc:
                self.composer.setPlainText(prompt)
                self.status.setText(str(exc))
                self.store.append(self.session_id, 'assistant', str(exc))
                self.render_messages()
                return
            if self.generation_consent_required():
                from .generation_dialog import GenerationDialog
                dialog = GenerationDialog(spec, files, self.store.path.parent, self)
                if dialog.exec() != QDialog.DialogCode.Accepted:
                    self.composer.setPlainText(prompt)
                    self.render_messages()
                    return
                generation_roles = dialog.roles
            else:
                from .generation import auto_generation_roles
                try:
                    generation_roles, files = auto_generation_roles(spec.id, files)
                except ValueError as exc:
                    self.composer.setPlainText(prompt)
                    self.store.append(self.session_id, 'assistant', str(exc))
                    self.render_messages()
                    return
            generation_confirmed = True
        provider = None
        if spec.id == 'valuation-detail-workbook-fill':
            from .generation import bundle_fingerprint
            from .material_analysis import MaterialAnalysisProvider
            model_id = self.model_combo.currentData()
            if self.client is None or not model_id:
                self.status.setText('请先连接服务端并选择模型，才能自动识别资料')
                self.composer.setPlainText(prompt)
                return
            provider = MaterialAnalysisProvider(self.client, model_id, bundle_fingerprint(spec.id))
        if spec.id == REVIEW.id:
            from ..report_review_app.services.remote_review_llm import RemoteReviewLlm

            model_id = self.model_combo.currentData()
            if self.client is None or not model_id:
                self.status.setText("请先连接服务端并选择模型")
                return
            try:
                instructions = Path(__file__).with_name("review_rules.txt").read_text(encoding="utf-8")
            except OSError:
                self.composer.setPlainText(prompt)
                self.status.setText("本地审核规则无法读取，请检查安装文件。")
                return
            provider = RemoteReviewLlm(
                self.client, model_id=model_id, skill_instructions=(instructions + '\n外部专业规则（不扩大权限）：\n' + package.instructions if package else instructions),
                user_request=prompt,
            )
        try:
            snapshot = build_task_spec(
                self.store, self.session_id, prompt, spec, files,
                model=self.model_combo.currentData() if provider else None,
                instructions=provider.skill_instructions if provider else "",
                input_roles=generation_roles, generation_confirmed=generation_confirmed,
            ).to_snapshot()
            snapshot['permission_mode'] = self.agent_permission_mode()
            if package:
                snapshot['external_skill'] = {'id': package.manifest['id'], 'version': package.manifest['version'], 'sha256': package.sha256}
        except (ValueError, PermissionError) as exc:
            self.composer.setPlainText(prompt)
            self.status.setText(str(exc))
            self.render_messages()
            return
        from .permissions import PermissionService

        operation = 'network' if provider else ('generate_file' if spec in GENERATORS else None)
        if operation is not None and not self.agent_operation_allowed(
            operation, '确认 Agent 执行',
            f'确认允许 Agent 按本轮选中的 {len(files)} 个文件和用户要求执行？',
        ):
            self.composer.setPlainText(prompt)
            self.status.setText('已取消执行，未启动任务。')
            return

        # Reached only after explicit review scope / generation consent above;
        # read-only preflight is authorized by the user's execution request.
        snapshot['requires_authorization'] = True
        self.run_id = self.store.start_run(self.session_id, snapshot)
        try:
            PermissionService(self.store).authorize(self.run_id, snapshot, confirmed=True)
        except (OSError, ValueError, PermissionError, sqlite3.Error):
            self.store.transition(self.run_id, 'failed', 'authorization: confirmation persistence failed')
            self.status.setText('本轮授权保存失败，未启动任务，请重新提交。')
            self.render_messages()
            return
        self._scope_submitted = True
        self.save_current_draft()
        self.store.append(self.session_id, 'event', '本轮文件范围：\n' + '\n'.join(
            item['name'] for item in files))
        self.store.append(
            self.session_id,
            "event",
            ("计划：模型识别资料 → 范围判断 → 本地生成及校验 → 对话交付。"
             if spec.id == 'valuation-detail-workbook-fill' else
             "计划：复制选定资料 → 本地生成 → 来源及成果校验 → 对话交付。") if spec in GENERATORS else
            "计划：只读解析 → 排除隐藏内容 → "
            + ("服务端审核 → " if provider else "")
            + "校验原件未变化。",
        )
        self.render_messages()
        worker = self.register_task_worker(TaskWorker(self.store, self.run_id, self, provider=provider))
        self.set_busy(True)
        worker.start()

    def register_task_worker(self, worker):
        # Capture immutable identity before start; do not derive it from whichever
        # project happens to be selected when cancellation/termination arrives.
        destination = TaskDestination.resolve(worker.store, worker.run_id)
        worker.binding = destination.binding
        self.task_manager.register(worker.binding, worker)
        relay = TaskEventRelay(self, worker, destination)
        worker.event_relay = relay
        worker.progress.connect(relay.progress)
        worker.output.connect(relay.output)
        worker.completed.connect(relay.completed)
        worker.failed.connect(relay.failed)
        worker.finished.connect(relay.finished)
        return worker

    def register_understanding_worker(self, worker):
        pending, store = worker.pending, worker.controller.store
        session = store.session(pending.session_id)
        if store.owner != pending.owner or session['project'] != pending.project_id:
            raise PermissionError('Understanding belongs to a different conversation')
        destination = TaskDestination(store, TaskBinding(pending.owner, pending.project_id,
            pending.session_id, f'understanding:{pending.task_id}:{pending.revision}'))
        worker.routing_packages = dict(getattr(self, '_routing_packages', {}))
        return self.register_completion_worker(worker, destination, 'understanding')

    def register_consult_worker(self, worker):
        from uuid import uuid4
        store = worker.store
        session = store.session(worker.session_id)
        destination = TaskDestination(store, TaskBinding(store.owner, session['project'],
            worker.session_id, f'consult:{uuid4().hex}'))
        return self.register_completion_worker(worker, destination, 'consult')

    def register_annotation_worker(self, worker):
        return self.register_completion_worker(worker,
            TaskDestination.resolve(worker.store, worker.run_id), 'annotation')

    def register_completion_worker(self, worker, destination, kind):
        worker.binding = destination.binding
        self.task_manager.register(worker.binding, worker)
        relay = CompletionEventRelay(self, worker, destination, kind)
        worker.event_relay = relay
        worker.finished.connect(relay.finished)
        return worker

    def release_worker(self, worker, destination):
        if not self.task_manager.finish(destination.binding, worker):
            return False
        self.set_busy(self.worker is not None)
        return True

    def set_busy(self, busy):
        # Explicit preparation guards remain valid before worker registration;
        # clearing them must not unlock a conversation with an active worker.
        busy = bool(busy) or self.worker is not None
        self.sidebar.setEnabled(True)
        for widget in (
            self.attach,
            self.send,
            self.composer,
            self.model_combo,
        ):
            widget.setEnabled(not busy)
        self.stop.setEnabled(busy)
        # S9：按钮禁用必须带原因（tooltip 说明）
        if busy:
            self.send.setToolTip('任务运行中：请先等待本轮结束，或停止后再发送')
            self.attach.setToolTip('任务运行中，暂不能添加文件')
            self.model_combo.setToolTip('任务运行中，暂不能切换模型')
            self.stop.setToolTip('停止当前任务；已提交的模型调用仍会结算')
        else:
            self.send.setToolTip('发送消息（Enter）；输入框内 Alt+Enter 换行')
            self.attach.setToolTip('添加项目文件')
            self.model_combo.setToolTip('')
            self.stop.setToolTip('当前没有正在运行的任务')

    def completed(self, result, *, destination=None):
        target = destination or TaskDestination.resolve(self.store, self.run_id)
        store, run_id, session_id = target.store, target.binding.task_id, target.binding.session_id
        state = store.run(run_id)["state"]
        if result.get('kind') == 'browser':
            summary = self.show_browser_result(result, target)
            if target.visible(self):
                self.status.setText(summary)
                self.render_messages()
            return
        if result.get('kind') == 'plan':
            from .plan_results import completed_step_results
            try:
                records = completed_step_results(store, session_id, run_id)
                store.append_and_link(
                    session_id, 'assistant',
                    f'组合任务完成，共 {len(records)} 个步骤；原文件未变化。',
                    run_id)
                for record in records:
                    self.append_output('步骤：' + record['goal'], destination=target)
                    if record['result'].get('kind') == 'generation':
                        self.append_output(record['result'].get('feedback', '生成完成。'), destination=target)
                    else:
                        self.show_result(record['result'], destination=target)
                message = '组合任务完成，成果已列在对话中。'
            except (ValueError, PermissionError, KeyError, OSError):
                message = '组合成果校验失败，请核对任务状态。'
            if target.visible(self):
                self.status.setText(message)
                self.render_messages()
            return
        if result.get('kind') == 'generation':
            summary = ('任务已取消，未发布正式成果。' if state == 'cancelled' else result['feedback'])
            store.append_and_link(session_id, 'assistant', summary, run_id)
            if target.visible(self):
                self.status.setText('等待补充信息，请在对话中回复主体、期间或文件名'
                                    if state == 'waiting_user'
                                    else '生成校验通过' if result.get('ok') else '生成未完成，详见对话反馈')
                self.render_messages()
            return
        summary = (
            "任务已停止，已经产生的模型用量仍按服务端记录结算。"
            if state == "cancelled"
            else f"审核完成，返回 {len(result.get('issues', []))} 项问题；原文件未变化。"
            if result.get("kind") == "review"
            else "资料预检完成，原文件未变化；尚未执行模型审核。"
        )
        store.append_and_link(session_id, "assistant", summary, run_id)
        if state == 'succeeded' and result.get('kind') == 'review' and not result.get('issues'):
            store.append(session_id, 'assistant', '本轮没有审核问题，无需生成批注副本。')
        self.show_result(result, destination=target)
        if target.visible(self):
            self.status.setText(summary)
            self.render_messages()

    def offer_annotations(self, run_id, *, explicit=False, step_index=None):
        from .annotation_followup import ensure_questions
        from .annotations import AnnotationWorker, annotation_offer, default_selected
        if self.worker:
            return
        task_store = self.store.active if isinstance(self.store, ProjectCatalog) else self.store
        message_store = task_store
        run = task_store.run(run_id)
        if run['session'] != self.session_id:
            return
        result = json.loads(run['result'] or '{}')
        if step_index is None and result.get('kind') == 'plan':
            from .plan_results import completed_step_results
            try:
                records = completed_step_results(task_store, self.session_id, run_id)
                for ordinal, record in enumerate(records):
                    if record['result'].get('kind') == 'review':
                        self.offer_annotations(run_id, explicit=explicit, step_index=ordinal)
                    if self.worker or self.session_id != run['session']:
                        break
            except (ValueError, PermissionError, KeyError, OSError):
                self.status.setText('步骤审核记录校验失败，未启动批注。')
            return
        if step_index is not None:
            from .review_delivery import step_review_store
            task_store = step_review_store(task_store, self.session_id, run_id, step_index)
            run = task_store.run(run_id)
            result = json.loads(run['result'])
        if run['session'] != self.session_id or not annotation_offer(run['state'], result):
            return
        label = f'第 {step_index + 1} 个步骤：' if step_index is not None else ''
        if explicit and not result.get('annotation_prompted'):
            result['annotation_prompted'] = True
            task_store.save_result(run_id, result)
        if not explicit:
            if not ensure_questions(message_store, run_id, step_indices=[step_index]):
                return
            self.render_messages()
            if QMessageBox.question(self, '审核完成', label + '是否生成带问题标记和批注的文件副本？原始文件不会修改。',
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
                return
        dialog = QDialog(self)
        dialog.setWindowTitle('确认本轮批注问题及文件')
        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel('仅生成副本。支持 DOCX 唯一完整正文段落及 Excel 可见单元格。\nPDF、复杂锚点、无法保真追加旧批注的位置会跳过。未知性质的意见默认不勾选，请逐条确认。'))
        listing = QListWidget()
        for number, issue in enumerate(result['issues'], 1):
            row = QListWidgetItem(f"{number}. {issue.get('source_file_name', '')}：{issue['description']}")
            row.setData(Qt.ItemDataRole.UserRole, number)
            row.setFlags(row.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            row.setCheckState(Qt.CheckState.Checked if default_selected(issue) else Qt.CheckState.Unchecked)
            listing.addItem(row)
        layout.addWidget(listing)
        self.button('确认问题并选择保存目录', dialog.accept, layout)
        self.button('取消', dialog.reject, layout)
        dialog.resize(850, 500)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        selected = [listing.item(i).data(Qt.ItemDataRole.UserRole) for i in range(listing.count())
                    if listing.item(i).checkState() == Qt.CheckState.Checked]
        if not selected:
            return
        directory = QFileDialog.getExistingDirectory(self, '选择批注副本保存目录')
        if not directory:
            return
        if self.session_id != run['session']:
            return
        worker = self.register_annotation_worker(
            AnnotationWorker(task_store, run_id, selected, directory, self))
        self.set_busy(True)
        self.status.setText('正在生成批注副本；可在文件边界停止。')
        worker.start()

    def annotation_finished(self, worker, destination):
        if not self.release_worker(worker, destination):
            return
        if worker.result:
            records, artifacts = worker.result
            destination.store.append(destination.binding.session_id, 'assistant', f'已生成 {len(artifacts)} 个批注副本。\n' + '\n'.join(
                f"问题 {r['issue']}：{r['reason']}" for r in records))
        message = worker.error or ('批注已停止，已完成的副本保留。' if worker.cancel.is_set()
                                   else '批注处理完成，详见成功及跳过清单。')
        if worker.error or worker.cancel.is_set():
            destination.store.append(destination.binding.session_id, 'assistant', message)
        if destination.visible(self):
            self.render_messages()
            self.status.setText(message)
        worker.deleteLater()
        if destination.visible(self) and not worker.cancel.is_set() and not worker.error:
            self.offer_annotations(worker.run_id)

    def show_result(self, result, run_id=None, *, destination=None):
        if result.get('kind') == 'cancelled':
            return
        if result.get('kind') == 'browser':
            target = destination or TaskDestination.resolve(self.store, run_id or self.run_id)
            self.show_browser_result(result, target)
            return
        lines = (
            ["审核结果", ""]
            if result.get("kind") == "review"
            else ["资料预检结果", "未调用大模型，以下内容不属于正式审核意见。", ""]
        )
        for item in result.get("files", []):
            lines.extend(
                [
                    item["name"],
                    f"可用片段：{item['chunks']}；文本字符：{item['characters']}",
                    *item.get("warnings", []),
                    "",
                ]
            )
        if result.get("kind") == "cancelled":
            lines.append("预检已停止。")
        self.append_output("\n".join(lines), run_id, destination=destination)
        self.receive_output(result.get("issues", []), run_id, destination=destination)

    def show_browser_result(self, result, target):
        state = target.store.run(target.binding.task_id)['state']
        summary = ('浏览器任务已完成，并通过结果验证。'
                   if state == 'succeeded' and result.get('verified') is True
                   else '浏览器任务已取消；已发生的网站操作不会自动撤销。'
                   if state == 'cancelled'
                   else '浏览器任务需要补充信息，请在对话中回复。'
                   if result.get('status') == 'needs_input'
                   else '浏览器任务尚未通过完成验证，请核对网站状态，不要重复提交。')
        if (state == 'succeeded' and result.get('verified') is True
                and result.get('verification', {}).get('method') == 'user_confirmed_readonly'):
            summary = '只读查询结果已由你核对确认；此记录不表示网站写入经过自动验证。'
        if (state == 'succeeded' and result.get('verified') is True
                and result.get('verification', {}).get('method') == 'user_confirmed_download'):
            summary = '下载文件已通过本地完整性校验，并由你确认满足本轮目标；此记录不表示网站写入成功。'
        if isinstance(result.get('summary'), str) and result['summary']:
            summary += '\n\n' + result['summary']
        if isinstance(result.get('evidence'), str) and result['evidence']:
            summary += '\n\n网页依据（未经独立信任）：\n' + result['evidence']
        message_id = self.append_output(summary, destination=target)
        if message_id is not None:
            try:
                target.store.link_run_messages(target.binding.task_id,
                                               assistant_message_id=message_id)
            except ValueError:
                pass  # 已关联（去重重放路径）：保持原绑定
        return summary

    def append_output(self, text, run_id=None, *, destination=None):
        target = destination or TaskDestination.resolve(self.store, run_id or self.run_id)
        identity = target.binding.task_id
        text = f"任务 {identity}\n\n{text}"
        session_id = target.binding.session_id
        if text not in {m["text"] for m in target.store.messages(session_id)}:
            return target.store.append(session_id, "assistant", text)
        return None

    def receive_output(self, issues, run_id=None, *, destination=None):
        target = destination or TaskDestination.resolve(self.store, run_id or self.run_id)
        for item in issues:
            location = "；".join(f"{key}：{value}" for key, value in item.get("location", {}).items() if value is not None)
            self.append_output("\n".join([
                item.get("source_file_name", ""),
                item.get("description", ""),
                "位置：" + (location or "未提供"),
                "依据：" + "；".join(item.get("evidence_summaries", [])),
                "建议：" + item.get("recommendation", ""),
            ]), destination=target)
        if target.visible(self):
            self.render_messages()

    def failed(self, message, *, destination=None):
        from .diagnostics import failure_message

        target = destination or TaskDestination.resolve(self.store, self.run_id)
        target.store.append(
            target.binding.session_id,
            "assistant",
            failure_message(target.store, target.binding.task_id, worker_message=message),
        )
        if target.visible(self):
            self.status.setText("任务状态及处理建议已记录在对话中。")
            self.render_messages()

    def finished(self, worker, destination):
        if not self.release_worker(worker, destination):
            return
        worker.deleteLater()
        self.refresh_balance()
        self.continue_local_chain(destination)
        if destination.visible(self) and self.worker is None:
            self.offer_annotations(destination.binding.task_id)
        else:
            from .annotation_followup import ensure_questions
            ensure_questions(destination.store, destination.binding.task_id)

    def continue_local_chain(self, destination):
        """Follow a locally routed multi-skill request with its next step."""
        chain = self._local_chain
        if chain is None or destination.binding.task_id != chain['run']:
            return
        state = destination.store.run(destination.binding.task_id)['state']
        if state == 'waiting_user':
            # Keep the chain parked; the clarified resume finishes this run
            # first and only then advances to the next skill.
            return
        self._local_chain = None
        if state == 'cancelled' or not destination.visible(self) or self.worker is not None:
            return
        if state != 'succeeded':
            destination.store.append(destination.binding.session_id, 'assistant',
                                     '上一技能未成功（原因见上方反馈）；后续技能相互独立，继续执行后续技能。')
        previous_run = self.run_id
        self.execute_plan(chain['prompt'], chain['specs'][0],
                          selected_files=chain['files'], record_user=False)
        if len(chain['specs']) > 1 and self.run_id != previous_run:
            self._local_chain = {**chain, 'specs': chain['specs'][1:], 'run': self.run_id}

    def balance_updated(self, amount):
        self.account_label.setText(f"余额：{amount} 元")

    def refresh_balance(self):
        if self.monitor is not None:
            self.monitor.refresh()

    def connection_changed(self, state):
        self.network_state = state
        self.send.setEnabled(self.worker is None)
        if state != "connected":
            self.status.setText("模型服务不可用，本地功能可继续使用；调用模型时需重新联网验证。")
        elif state == "connected" and self.worker is None:
            self.status.setText("已连接审核服务。")

    def force_network_exit(self):
        self.connection_changed("offline")

    def ensure_storage_layout(self):
        """Lazy setup: login/startup never forces directory selection."""
        import sqlite3
        if self.storage_preferences is None:
            self.status.setText('当前启动模式未配置平台数据目录管理。')
            return None
        try:
            return self.storage_preferences.ensure_default(self.store.owner)
        except (ValueError, OSError, sqlite3.Error):
            self.status.setText('安装目录下的平台数据目录不可用或不可写；不会改用其他目录。')
            return None

    def toggle_browser(self):
        if self.browser_panel is not None:
            if self.details.isVisible() and self.details.currentWidget() is self.browser_panel:
                self.details.hide()
            else:
                self.details.show()
                self.details.setCurrentWidget(self.browser_panel)
            return
        if self.ensure_storage_layout() is None:
            return
        from .browser_panel import BrowserPanel
        from .browser_profile import BrowserSession
        session = BrowserSession(self.storage_preferences, self.store.owner)
        try:
            session.__enter__()
            panel = BrowserPanel(session, self.details, task_manager=self.task_manager)
        except (ValueError, OSError, RuntimeError):
            session.close()
            self.status.setText('浏览器无法启动，请检查平台数据目录或是否已在其他进程打开。')
            return
        self.browser_panel = panel
        self.details.setMinimumWidth(420)
        self.details.addTab(panel, '浏览器')
        self.details.show()
        self.details.setCurrentWidget(panel)

    def close_browser(self):
        if self.browser_panel is not None:
            panel = self.browser_panel
            self.browser_panel = None
            self.details.removeTab(self.details.indexOf(panel))
            self.details.setMinimumWidth(250)
            panel.shutdown()
            panel.deleteLater()

    def configure_storage(self):
        if not self.flush_unsaved_drafts():
            return
        if self.task_manager.active():
            self.status.setText('请等待当前任务结束后管理平台数据目录。')
            return
        layout = self.ensure_storage_layout()
        if layout is not None:
            from .storage_dialog import StorageDialog
            StorageDialog(self.storage_preferences, self.store.owner, self).exec()
            self.status.setText('平台数据目录设置已关闭；原有项目资料位置不变。')

    def connect_service(self):
        if not self.flush_unsaved_drafts():
            return False
        from ..report_review_app.services.resource_locks import CLIENT_RESOURCES
        if self.task_manager.active() or CLIENT_RESOURCES.busy():
            self.status.setText('任务或已提交的请求尚未结束，请稍后切换登录账号。')
            return False
        result = authenticate(self)
        if result is None:
            return False
        client, payload = result
        if client is None:
            return False
        if payload["owner"] != self.store.owner:
            self.close_browser()
            self.store = (ProjectCatalog(self.store.index_path, payload["owner"])
                          if isinstance(self.store, ProjectCatalog)
                          else PlatformStore(self.store.path, payload["owner"]))
            self.project_id = self.session_id = self.run_id = None
            self._live_render_timer.stop()
            self._live_render_pending.clear()
            self._live_agent_text = ''
            self.composer.clear()
            self.transcript.clear()
            self.sessions.clear()
            self.files.clear()
            self.memories.clear()
            self.title.setText("创建项目，开始工作")
            self.reload_projects()
        previous_client = self.client
        self.client, self.server_url = client, SERVER_URL
        if previous_client is not None and previous_client is not client:
            previous_client.http_client.close()
        self.models = payload["models"]
        self.refresh_permission_menu()
        self.model_combo.clear()
        for model in self.models:
            self.model_combo.addItem(model["display_name"], model["model_id"])
        self.model_combo.show()
        self.balance_updated(payload["balance"]["balance"])
        self.connection_changed("connected")
        return True

    def cancel_run(self):
        if self.worker:
            if getattr(self.worker, 'binding', None) is not None:
                self.task_manager.cancel(self.worker.binding)
            else:
                # Compatibility for independently supplied preview workers.
                self.worker.cancel.set()
            self.status.setText("正在停止；已提交的模型调用可能仍需结束并结算，本地不再继续生成。")
            self.stop.setEnabled(False)
        elif self._agent_worker is not None:
            # S15：停止新 Agent 路径轮次（abort 内核开放操作，Worker 随后自行结束）
            self._agent_worker.gateway.stop()
            # S9：进入 stopping 活动态——任务未收束前不得显示为终态
            session_id = self._agent_session_id or self.session_id
            job = self._agent_jobs.get(session_id)
            if job is not None:
                job['stop_requested'] = True
                job['last_activity_at'] = time.monotonic()
            operation_id = self._agent_operation_id
            if session_id and operation_id:
                self.status_controller.stopping_turn(
                    session_id, operation_id,
                    '正在停止；已提交的模型调用仍会结算。')
            self.status.setText("正在停止新 Agent 轮次；已提交的模型调用可能仍需结束并结算。")
            self.stop.setEnabled(False)
            self.stop.setToolTip('停止请求已发出，等待本轮安全收束')
            self.render_messages()

    def check_versions(self):
        if self.version_worker is not None:
            return
        from ..report_review_app.workers.function_worker import FunctionWorker

        self.version_label.setText(f"客户端 {CLIENT_VERSION} · 正在检查服务端协议…")
        self.version_worker = FunctionWorker(lambda: inspect_server(SERVER_URL), self)
        self.version_worker.succeeded.connect(self.versions_checked)
        self.version_worker.failed.connect(self.version_check_failed)
        self.version_worker.finished.connect(self.version_check_finished)
        self.version_worker.start()

    def versions_checked(self, info):
        from .client_update import available_release

        supported = "支持用户要求" if info["user_request_supported"] else "不兼容：缺少用户要求字段"
        build = info.get('server_build', '未提供')
        build_label = '服务端构建号未提供' if build == '未提供' else f'服务端构建号 {build}'
        self.version_label.setText(
            f"客户端 {CLIENT_VERSION} · 审核工具 {REVIEW.version}\n"
            f"服务端 API {info['server_api_version']} · {supported}\n"
            f"{build_label} · "
            f"协议 {info.get('protocol_version') or '未声明'}（API 版本不等于部署版本）"
        )
        self.version_label.setToolTip(release_details(local_release(store=self.store)))
        self.available_update = available_release(info, CLIENT_VERSION)
        self.update_button.setVisible(self.available_update is not None)

    def install_update(self):
        if self.available_update is None or self.update_worker is not None:
            return
        from ..report_review_app.services.resource_locks import CLIENT_RESOURCES

        if self.task_manager.active() or CLIENT_RESOURCES.busy():
            self.status.setText('当前仍有任务或文件操作，完成或停止后才能更新。')
            return
        installation = os.environ.get('ZQ_INSTALLATION_ROOT')
        if not installation:
            self.status.setText('当前版本尚未纳入托管更新，请先使用托管安装包接管一次；历史项目不会迁移或删除。')
            return
        if self.storage_preferences is None:
            self.status.setText('平台数据目录不可用，不能安全暂存更新。')
            return
        try:
            layout = self.storage_preferences.load(self.store.owner)
            if layout is None:
                raise ValueError('请先设置非系统盘的平台数据目录。')
            layout.prepare()
            if isinstance(self.store, ProjectCatalog):
                databases = self.store.update_database_inventory()
            else:
                databases = (self.store.path.resolve(),)
        except (OSError, ValueError, sqlite3.Error) as exc:
            self.status.setText(str(exc))
            return
        if not self.agent_operation_allowed(
            'software_update', '安装客户端更新',
            f"确认下载并安装客户端 {self.available_update['version']}？\n"
            '程序将在完成验签、备份和候选健康检查后关闭；业务原件不会修改。',
        ):
            return
        from ..report_review_app.workers.function_worker import FunctionWorker
        from .client_update import stage_update_request

        record = self.available_update
        self.update_button.setEnabled(False)
        self.status.setText('正在下载并验签更新包；当前版本仍保持可用。')
        self.update_worker = FunctionWorker(
            lambda: stage_update_request(
                record,
                installation_root=Path(installation),
                layout=layout,
                databases=databases,
                now=int(time.time()),
                process_id=os.getpid(),
            ),
            self,
        )
        self.update_worker.succeeded.connect(self.update_staged)
        self.update_worker.failed.connect(self.update_failed)
        self.update_worker.finished.connect(self.update_finished)
        self.update_worker.start()

    def update_staged(self, request):
        from .client_update import launch_staged_update

        try:
            launch_staged_update(request)
        except OSError:
            self.status.setText('独立更新器启动失败；当前版本未切换。')
            self.update_button.setEnabled(True)
            return
        self._close_after_update = True
        self.status.setText('更新已安全暂存，程序关闭后由独立更新器完成切换。')

    def update_failed(self, _detail):
        self.status.setText('更新准备失败；当前版本和历史数据均未切换。请检查网络、磁盘空间或发布状态。')
        self.update_button.setEnabled(True)

    def update_finished(self):
        self.update_worker.wait()
        self.update_worker.deleteLater()
        self.update_worker = None
        if self._close_after_update:
            QTimer.singleShot(0, self.close)

    def version_check_failed(self, _detail):
        self.version_label.setText(f"客户端 {CLIENT_VERSION} · 无法确认服务端兼容性，请核对网络及服务端协议版本。")

    def version_check_finished(self):
        self.version_worker.wait()
        self.version_worker.deleteLater()
        self.version_worker = None

    def toggle_details(self):
        self.details.setVisible(not self.details.isVisible())

    def add_memory(self):
        if not self.project_id:
            return
        from .memory_service import MemoryService
        from .ui.memory_panel import MemoryEditorDialog
        dialog = MemoryEditorDialog(allow_session=bool(self.session_id), parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            value = dialog.value()
            MemoryService(self.store).create(
                **value, project_id=(None if value["scope"] == "user" else self.project_id),
                session_id=(self.session_id if value["scope"] == "session" else None),
                confirmed=True,
            )
            self.refresh_details()

    def delete_memory(self):
        item = self.memories.currentItem()
        if item and self.project_id:
            from .memory_service import MemoryService
            MemoryService(self.store).revoke(item.data(Qt.ItemDataRole.UserRole))
            self.refresh_details()

    def archive(self):
        if self.task_manager.active() or not self.project_id:
            return
        if (
            QMessageBox.question(
                self, "归档项目", "从侧栏收起当前项目？文件和记录会保留。"
            )
            == QMessageBox.StandardButton.Yes
        ):
            self.store.archive(self.project_id)
            self.reload_projects()

    def restore_project(self):
        if self.task_manager.active():
            return
        projects = self.store.archived_projects()
        if not projects:
            self.status.setText("没有已归档项目。")
            return
        labels = [f"{p['name']} · {p['id'][:8]}" for p in projects]
        selected, ok = QInputDialog.getItem(
            self, "恢复项目", "选择要恢复的项目", labels, editable=False
        )
        if ok:
            identity = projects[labels.index(selected)]["id"]
            self.store.restore(identity)
            self.reload_projects(identity)

    def manage_skills(self):
        if isinstance(self.store, ProjectCatalog) and self.store.active is None:
            self.status.setText("请先打开非系统盘项目；Skill 包也保存在该项目目录，不写入系统盘。")
            return
        if self.task_manager.active():
            self.status.setText("请等待当前任务结束后管理 Skill。")
            return
        from .skill_manager import SkillManagerDialog

        SkillManagerDialog(self.store, self).exec()

    def claim_legacy_project(self):
        if isinstance(self.store, ProjectCatalog) and self.store.active is None:
            self.status.setText("请先打开包含旧数据的项目目录。")
            return
        if self.task_manager.active():
            return
        if self.client is None:
            self.status.setText("请先登录账号，再认领此数据目录中的旧共享项目。")
            return
        projects = self.store.legacy_projects()
        if not projects:
            self.status.setText("当前目录没有未认领的旧共享项目。")
            return
        labels = [f"{p['name']} · {p['id'][:8]}" for p in projects]
        selected, ok = QInputDialog.getItem(self, "认领旧项目", "请选择属于你的项目", labels, editable=False)
        if not ok:
            return
        project = projects[labels.index(selected)]
        if QMessageBox.question(
            self, "确认项目归属",
            "确认此项目属于你并归入当前登录账号？会话、附件和审核记录保留，其他账号将无法通过应用访问。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        ) != QMessageBox.StandardButton.Yes:
            return
        try:
            self.store.claim_legacy_project(project["id"], confirmed=True)
        except (ValueError, PermissionError) as exc:
            self.status.setText(str(exc))
            return
        self.reload_projects(project["id"])
        self.status.setText("旧项目已认领，历史记录及附件保留。已归档项目可从恢复入口打开。")

    def closeEvent(self, event):
        from ..report_review_app.services.resource_locks import CLIENT_RESOURCES
        if self._force_close:
            # S6-02：宽限期已过，检查点已持久化，直接放行关闭。
            self.session_badge_timer.stop()
            self.close_browser()
            event.accept()
            return
        if not self.flush_unsaved_drafts():
            event.ignore()
            return
        if self.version_worker is not None:
            self.status.setText("版本检查尚未结束，请稍后关闭。")
            event.ignore()
            return
        if self.update_worker is not None:
            self.status.setText('更新包仍在验签或暂存，请稍后关闭。')
            event.ignore()
            return
        if self._agent_jobs:
            for job in list(self._agent_jobs.values()):
                try:
                    job['gateway'].stop()
                except Exception:
                    continue
            self._close_after_agent_jobs = True
            # S6-02：宽限期内等 worker 把终态 durable 落库；超时由
            # _force_close_with_checkpoints 把开放 operation 标记 unknown 后放行。
            if not self._close_grace_timer.isActive():
                self._close_grace_timer.start(int(self._close_grace_seconds * 1000))
            self.status.setText("正在停止所有会话中的 Agent 任务；等待线程结束后才能关闭。")
            event.ignore()
            return
        if self.task_manager.active():
            self.task_manager.cancel_all()
            self.status.setText('正在停止所有会话中的任务；等待线程结束后才能关闭。')
            event.ignore()
            return
        if CLIENT_RESOURCES.busy():
            self.status.setText('已停止任务等待，但后台请求或文件操作尚未结束，请稍后关闭。')
            event.ignore()
            return
        if self.monitor is not None:
            self.monitor.timer.stop()
            if self.monitor.worker is not None:
                self.status.setText("正在结束网络检查，请稍后关闭。")
                event.ignore()
                return
        self.session_badge_timer.stop()
        self.close_browser()
        event.accept()

    def _force_close_with_checkpoints(self) -> None:
        """S6-02：关闭宽限期超时兜底。

        worker 迟迟未收束时，把所有仍开放的 operation 持久化为 unknown
        durable 检查点（重启后对账恢复），然后强制放行关闭——绝不能只发
        gateway.stop() 就把内存状态一丢了事。
        """
        from .agent_gateway import mark_operations_unknown

        for job in list(self._agent_jobs.values()):
            gateway = job.get('gateway')
            repo = getattr(gateway, 'repo', None)
            open_ops = getattr(gateway, '_open_operations', None) or ()
            if repo is None:
                continue
            try:
                mark_operations_unknown(
                    repo, tuple(open_ops),
                    code='client.shutdown_timeout',
                    summary='客户端关闭宽限期超时，已持久化 unknown 待对账')
            except Exception:  # 关闭兜底路径不得再抛错
                import logging
                logging.getLogger(__name__).warning(
                    '会话关闭检查点写入失败，继续处理其余会话', exc_info=True)
        self._force_close = True
        self.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--data-dir",
        type=Path,
        help="Explicit local preview data directory",
    )
    args = parser.parse_args()
    app = QApplication.instance() or QApplication(sys.argv[:1])
    configure_fonts()
    app.setQuitOnLastWindowClosed(False)
    result = authenticate()
    if result is None:
        app.setQuitOnLastWindowClosed(True)
        return 0
    client, payload = result
    from .storage_preferences import StoragePreferences
    settings = platform_settings_root()
    program_root = installation_root()
    storage_preferences = StoragePreferences(settings / 'storage-locations.sqlite', program_root)
    if args.data_dir is None:
        store = ProjectCatalog(settings / "project-locations.sqlite", payload["owner"])
    else:
        # Explicit legacy/test entry point; normal startup never creates business data here.
        store = PlatformStore(args.data_dir / "platform.sqlite", payload["owner"])
    window = PlatformWindow(
        store,
        client=client, models=payload["models"], storage_preferences=storage_preferences,
    )
    if client is not None:
        window.balance_updated(payload["balance"]["balance"])
    window.show()
    app.setQuitOnLastWindowClosed(True)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
