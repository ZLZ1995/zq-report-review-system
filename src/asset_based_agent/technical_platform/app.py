"""Project-first local preview. Remote authentication is integrated separately."""

from __future__ import annotations

import argparse
import html
import json
import os
import sys
import threading
from pathlib import Path

from PySide6.QtCore import QEvent, QStandardPaths, Qt, QThread, Signal, QUrl
from PySide6.QtGui import QFont, QFontDatabase, QDesktopServices
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTabWidget,
    QTextBrowser,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from .skills import BUILTINS, GENERATORS, PREFLIGHT, REVIEW, SkillRegistry, digest
from .store import PlatformStore
from .project_catalog import ProjectCatalog
from .release_info import CLIENT_VERSION, inspect_server, local_release
from .task_spec import build_task_spec
from .execution import execute_task

SERVER_URL = "https://zq-report-review.zeabur.app/api/v1"


def authenticate(parent=None):
    """Login before workspace construction; users never configure an API endpoint."""
    from ..report_review_app.services.remote_auth_service import (
        RemoteSessionClient,
        WindowsCredentialStore,
        load_or_create_client_instance_id,
    )
    from .login import PlatformLogin
    from .session import PlatformSession

    state_dir = Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppLocalDataLocation)) / "ZQPlatform"
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

    def __init__(self, store, run_id, parent=None, provider=None):
        super().__init__(parent)
        self.store, self.run_id = store, run_id
        self.cancel = threading.Event()
        self.provider = provider

    def run(self):
        try:
            result = execute_task(
                self.store,
                self.run_id,
                self.cancel,
                self.progress.emit,
                provider=self.provider,
                output=self.output.emit,
            )
            self.completed.emit(result)
        except Exception as exc:  # noqa: BLE001 - worker boundary records failure and reports to UI
            # The harness owns state transitions; a rejected duplicate owns no run.
            self.failed.emit(str(exc))


class PlatformWindow(QMainWindow):
    def __init__(self, store: PlatformStore, *, client=None, models=None):
        super().__init__()
        configure_fonts()
        self.store = store
        self.client, self.models = client, models or []
        self.registry = SkillRegistry()
        for skill in BUILTINS:
            self.registry.register(skill)
        self.project_id = self.session_id = self.run_id = None
        self.worker = None
        self.monitor = None
        self.version_worker = None
        self.network_state = "connected"
        self.setWindowTitle(
            "ZQ 技术平台" + (" · 本地交互预览" if client is None else "")
        )
        self.resize(1440, 900)
        self.setMinimumSize(960, 640)
        self._build()
        self.reload_projects(self.store.last_project if isinstance(self.store, ProjectCatalog) else None)
        self.server_url = SERVER_URL

    def button(self, title, callback, layout):
        button = QPushButton(title)
        button.clicked.connect(callback)
        layout.addWidget(button)
        return button

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
        heading = QLabel("项目")
        heading.setObjectName("sectionLabel")
        left.addWidget(heading)
        self.projects = QListWidget()
        self.projects.setMaximumHeight(180)
        self.projects.currentItemChanged.connect(self.choose_project)
        left.addWidget(self.projects)
        left.addSpacing(12)
        session_header = QHBoxLayout()
        heading = QLabel("当前项目的会话")
        heading.setObjectName("sectionLabel")
        session_header.addWidget(heading, 1)
        self.button("＋", self.new_session, session_header).setToolTip("新建会话")
        left.addLayout(session_header)
        self.sessions = QListWidget()
        self.sessions.currentItemChanged.connect(self.choose_session)
        left.addWidget(self.sessions, 3)
        self.button("归档项目", self.archive, left).setObjectName("mutedButton")
        self.button("恢复已归档项目", self.restore_project, left).setObjectName(
            "mutedButton"
        )
        self.button("认领旧共享项目", self.claim_legacy_project, left).setObjectName("mutedButton")
        self.button("外部 Skill 管理", self.manage_skills, left).setObjectName("mutedButton")
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
        self.version_label = QLabel(f"客户端 {CLIENT_VERSION} · 审核 Skill {REVIEW.version}")
        self.version_label.setWordWrap(True)
        left.addWidget(self.version_label)
        self.button("检查服务版本兼容性", self.check_versions, left)
        splitter.addWidget(sidebar)

        center = QWidget()
        middle = QVBoxLayout(center)
        middle.setContentsMargins(32, 18, 32, 22)
        middle.setSpacing(14)
        top = QHBoxLayout()
        self.title = QLabel("创建项目，开始工作")
        self.title.setObjectName("title")
        top.addWidget(self.title, 1)
        self.button("项目面板", self.toggle_details, top).setObjectName("panelButton")
        middle.addLayout(top)
        self.transcript = QTextBrowser()
        self.transcript.setObjectName("transcript")
        self.transcript.setOpenExternalLinks(False)
        self.transcript.setOpenLinks(False)
        self.transcript.anchorClicked.connect(self.handle_report_link)
        middle.addWidget(self.transcript, 1)
        self.status = QLabel("请选择项目。此入口用于本地交互和只读资料预检。")
        self.status.setObjectName("status")
        self.status.setWordWrap(True)
        middle.addWidget(self.status)
        composer_card = QWidget()
        composer_card.setObjectName("composerCard")
        composer_layout = QVBoxLayout(composer_card)
        composer_layout.setContentsMargins(12, 10, 12, 10)
        composer_layout.setSpacing(4)
        self.composer = QTextEdit()
        self.composer.setObjectName("composer")
        self.composer.setFixedHeight(86)
        self.composer.setPlaceholderText(
            "描述你想完成的工作…\n例如：检查本项目的审核资料"
        )
        composer_layout.addWidget(self.composer)
        actions = QHBoxLayout()
        self.attach = self.button("＋", self.add_files, actions)
        self.attach.setToolTip("添加项目文件")
        self.attach.setFixedWidth(36)
        self.skill_combo = QComboBox()
        self.skill_combo.addItem("资料预检", PREFLIGHT.id)
        self.skill_combo.setToolTip("选择本次执行使用的 Skill；资料预检不调用模型")
        self.skill_combo.addItem(REVIEW.name, REVIEW.id)
        for skill in GENERATORS:
            self.skill_combo.addItem(skill.name, skill.id)
        if self.client is not None:
            self.skill_combo.setCurrentIndex(1)
        actions.addWidget(self.skill_combo)
        actions.addStretch(1)
        self.model_combo = QComboBox()
        for model in self.models:
            self.model_combo.addItem(model["display_name"], model["model_id"])
        self.model_combo.setVisible(self.client is not None)
        actions.addWidget(self.model_combo)
        self.stop = self.button("停止", self.cancel_run, actions)
        self.stop.setEnabled(False)
        self.send = self.button("执行 ↑", self.submit, actions)
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
        file_layout.addWidget(self.files, 1)
        self.details.addTab(file_page, "文件")
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
        splitter.addWidget(self.details)
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
            QListWidget { border:0; background:transparent; outline:0; padding:0; }
            QListWidget::item { padding:11px 10px; border-radius:8px; margin:2px 0; }
            QListWidget::item:hover { background:#ededf1; }
            QListWidget::item:selected { background:#e7e8ee; color:#252a37; }
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

    def new_project(self):
        if self.worker:
            return
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
        if self.worker or not isinstance(self.store, ProjectCatalog):
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
        self.project_id = item.data(Qt.ItemDataRole.UserRole) if item else None
        self.sessions.clear()
        self.files.clear()
        self.memories.clear()
        if not self.project_id:
            self.title.setText("创建项目，开始工作")
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
        self.status.setText("添加项目资料，选择 Skill 后执行。原始文件只读。")
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
        if self.worker:
            return
        if self.project_id:
            self.store.create_session(
                self.project_id, f"会话 {self.sessions.count() + 1}"
            )
            self.choose_project(self.projects.currentItem())

    def choose_session(self, item, _previous=None):
        self.session_id = item.data(Qt.ItemDataRole.UserRole) if item else None
        self.render_messages()
        if self.session_id:
            if isinstance(self.store, ProjectCatalog):
                self.store.remember_session(self.session_id)
            runs = self.store.runs(self.session_id)
            for run in runs:
                if run["result"]:
                    self.show_result(json.loads(run["result"]), run_id=run["id"])
            self.render_messages()

    def render_messages(self):
        scroll = self.transcript.verticalScrollBar()
        previous_position = scroll.value()
        follow_output = previous_position >= scroll.maximum() - 24
        rows = self.store.messages(self.session_id) if self.session_id else []
        content = []
        for message in rows:
            text = html.escape(message["text"]).replace("\n", "<br>")
            if message["role"] == "user":
                content.append(
                    '<table width="100%" cellspacing="0" cellpadding="16">'
                    '<tr><td width="12%"></td><td bgcolor="#f3f4f7">'
                    '<span style="color:#9399a6;font-size:11px">你</span>'
                    f'<p style="line-height:160%;font-size:14px">{text}</p>'
                    '</td></tr></table><p style="font-size:8px">&nbsp;</p>'
                )
            elif message["role"] == "event":
                content.append(
                    '<table width="100%" cellpadding="12"><tr>'
                    '<td bgcolor="#fafbfc"><span style="color:#758399;font-size:11px">'
                    "●  执行记录</span>"
                    f'<p style="color:#858d9b;font-size:12px;line-height:150%">{text}</p>'
                    '</td></tr></table><p style="font-size:8px">&nbsp;</p>'
                )
            else:
                content.append(
                    '<p style="font-size:13px;color:#3e4c66"><b>ZQ</b>'
                    ' <span style="font-size:10px;color:#a0a6b1"> / ASSISTANT</span></p>'
                    f'<p style="font-size:14px;line-height:170%;margin-bottom:28px">{text}</p>'
                )
        if self.session_id:
            for run in self.store.runs(self.session_id):
                result = json.loads(run['result'] or '{}')
                if result.get('kind') == 'generation':
                    for index, artifact in enumerate(result.get('artifacts', [])):
                        name = html.escape(artifact['name'])
                        content.append(f'<p>📄 {name}　<a href="zq-artifact:{run["id"]}/{index}">打开文件</a></p>')
                if run['state'] == 'succeeded' and result.get('kind') == 'review':
                    identity = run['id']
                    content.append(f'<p>审核任务 {html.escape(identity)}：<a href="zq-export:{identity}">生成标准Word审核报告…</a></p>')
                    if result.get('exported_report'):
                        name = html.escape(Path(result['exported_report']).name)
                        content.append(f'<p>📄 {name}　<a href="zq-report:{identity}">打开文件</a>　<a href="zq-folder:{identity}">打开所在文件夹</a></p>')
        self.transcript.setHtml(
            "".join(content)
            or (
                '<p style="margin-top:110px;color:#9ca3b2;font-size:12px">ZQ WORKSPACE</p>'
                '<p style="font-size:28px;color:#303745"><b>从一个项目，开始工作。</b></p>'
                '<p style="color:#8d95a3;font-size:14px;line-height:180%">'
                "整理资料，提出问题，让每一步执行都有迹可循。<br>"
                "添加项目文件后，选择一个 Skill 开始。</p>"
                '<p style="margin-top:28px;color:#647087;font-size:12px">'
                "项目上下文　 /　 只读资料预检　 /　 可追溯的执行记录</p>"
            )
        )
        scroll.setValue(scroll.maximum() if follow_output else previous_position)

    def handle_report_link(self, url):
        from .report_export import export_review
        action = url.scheme()
        if action == 'zq-artifact':
            try:
                from .generation import artifact_path
                run_id, index = url.path().split('/')
                path = artifact_path(self.store, self.session_id, run_id, int(index))
                if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(path))):
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

    def refresh_details(self):
        self.files.clear()
        self.memories.clear()
        if not self.project_id:
            return
        files = self.store.files(self.project_id)
        latest = {item["name"]: item["id"] for item in files}
        for item in files:
            row = QListWidgetItem(
                f"{item['name']}\n{item['size']:,} bytes · {item['sha256'][:10]}"
            )
            row.setData(Qt.ItemDataRole.UserRole, item["id"])
            row.setFlags(row.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            row.setCheckState(
                Qt.CheckState.Checked
                if latest[item["name"]] == item["id"]
                else Qt.CheckState.Unchecked
            )
            self.files.addItem(row)
        for item in self.store.memories(self.project_id):
            row = QListWidgetItem(item["text"])
            row.setData(Qt.ItemDataRole.UserRole, item["id"])
            self.memories.addItem(row)

    def add_files(self):
        if not self.project_id or not self.attach.isEnabled():
            return
        paths, _ = QFileDialog.getOpenFileNames(
            self, "添加项目资料", "", "资料 (*.docx *.xlsx *.xlsm *.pdf)"
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
        known = {(f["name"], f["sha256"]) for f in self.store.files(self.project_id)}
        added = skipped = 0
        errors = []
        for raw in paths:
            try:
                path = Path(raw).resolve()
                if path.is_dir():
                    errors.append(f"{path.name}：不支持文件夹")
                    continue
                if path.suffix.lower() not in {".docx", ".xlsx", ".xlsm", ".pdf"}:
                    errors.append(f"{path.name}：不支持的文件类型")
                    continue
                hashed = digest(path)
                if (path.name, hashed) not in known:
                    self.store.add_file(self.project_id, path, hashed)
                    known.add((path.name, hashed))
                    added += 1
                else:
                    skipped += 1
            except OSError:
                errors.append(f"{Path(raw).name}：文件无法读取或复制")
        if added:
            self.refresh_details()
            self.details.show()
            self.details.setCurrentIndex(0)
        message = f"已添加 {added} 个文件，跳过 {skipped} 个重复文件。点击执行后才开始任务。"
        if errors:
            message += "\n" + "；".join(errors)
        self.status.setText(message)

    def submit(self):
        if not self.session_id or self.worker:
            return
        prompt = self.composer.toPlainText().strip()
        if not prompt:
            return
        if (
            self.skill_combo.currentData() == REVIEW.id
            and (self.client is None or self.network_state != "connected")
            and not self.connect_service()
        ):
            return
        # Authentication may switch the owner and clear the previous session.
        if not self.session_id:
            self.status.setText("账号已切换，请选择当前账号的项目后重新输入任务。")
            return
        self.store.append(self.session_id, "user", prompt)
        self.composer.clear()
        files = self.store.files(self.project_id)
        selected_ids = {
            self.files.item(i).data(Qt.ItemDataRole.UserRole)
            for i in range(self.files.count())
            if self.files.item(i).checkState() == Qt.CheckState.Checked
        }
        files = [item for item in files if item["id"] in selected_ids]
        if not files:
            self.store.append(
                self.session_id, "assistant", "请先添加资料，再执行只读预检。"
            )
            self.render_messages()
            return
        spec = self.registry.get(self.skill_combo.currentData())
        generation_roles = None
        if spec in GENERATORS:
            from .generation import locked_template
            try:
                locked_template(spec.id)
            except (ValueError, OSError, PermissionError) as exc:
                self.composer.setPlainText(prompt)
                self.status.setText(str(exc))
                self.store.append(self.session_id, 'assistant', str(exc))
                self.render_messages()
                return
            from .generation_dialog import GenerationDialog
            dialog = GenerationDialog(spec, files, self.store.path.parent, self)
            if dialog.exec() != QDialog.DialogCode.Accepted:
                self.composer.setPlainText(prompt)
                self.render_messages()
                return
            generation_roles = dialog.roles
        provider = None
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
                self.client, model_id=model_id, skill_instructions=instructions,
                user_request=prompt,
            )
        try:
            snapshot = build_task_spec(
                self.store, self.session_id, prompt, spec, files,
                model=self.model_combo.currentData() if provider else None,
                instructions=provider.skill_instructions if provider else "",
                input_roles=generation_roles, generation_confirmed=generation_roles is not None,
            ).to_snapshot()
        except (ValueError, PermissionError) as exc:
            self.composer.setPlainText(prompt)
            self.status.setText(str(exc))
            self.render_messages()
            return
        self.run_id = self.store.start_run(self.session_id, snapshot)
        self.store.append(
            self.session_id,
            "event",
            "计划：复制选定资料 → 本地生成 → 来源及成果校验 → 对话交付。" if spec in GENERATORS else
            "计划：只读解析 → 排除隐藏内容 → "
            + ("服务端审核 → " if provider else "")
            + "校验原件未变化。",
        )
        self.render_messages()
        self.worker = TaskWorker(self.store, self.run_id, self, provider=provider)
        self.worker.progress.connect(self.status.setText)
        self.worker.output.connect(self.receive_output)
        self.worker.completed.connect(self.completed)
        self.worker.failed.connect(self.failed)
        self.worker.finished.connect(self.finished)
        self.set_busy(True)
        self.worker.start()

    def set_busy(self, busy):
        for widget in (
            self.sidebar,
            self.attach,
            self.send,
            self.composer,
            self.skill_combo,
            self.model_combo,
        ):
            widget.setEnabled(not busy)
        self.stop.setEnabled(busy)

    def completed(self, result):
        state = self.store.run(self.run_id)["state"]
        if result.get('kind') == 'generation':
            summary = ('任务已取消，未发布正式成果。' if state == 'cancelled' else result['feedback'])
            self.store.append(self.store.run(self.run_id)['session'], 'assistant', summary)
            self.status.setText('生成校验通过' if result.get('ok') else '生成未完成，详见对话反馈')
            self.render_messages()
            return
        summary = (
            "任务已停止，已经产生的模型用量仍按服务端记录结算。"
            if state == "cancelled"
            else f"审核完成，返回 {len(result.get('issues', []))} 项问题；原文件未变化。"
            if result.get("kind") == "review"
            else "资料预检完成，原文件未变化；尚未执行模型审核。"
        )
        self.store.append(self.store.run(self.run_id)["session"], "assistant", summary)
        self.status.setText(summary)
        self.show_result(result)
        self.render_messages()

    def show_result(self, result, run_id=None):
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
        self.append_output("\n".join(lines), run_id)
        self.receive_output(result.get("issues", []), run_id)

    def append_output(self, text, run_id=None):
        identity = run_id or self.run_id
        text = f"任务 {identity}\n\n{text}"
        if self.session_id and text not in {m["text"] for m in self.store.messages(self.session_id)}:
            self.store.append(self.session_id, "assistant", text)

    def receive_output(self, issues, run_id=None):
        for item in issues:
            location = "；".join(f"{key}：{value}" for key, value in item.get("location", {}).items() if value is not None)
            self.append_output("\n".join([
                item.get("source_file_name", ""),
                item.get("description", ""),
                "位置：" + (location or "未提供"),
                "依据：" + "；".join(item.get("evidence_summaries", [])),
                "建议：" + item.get("recommendation", ""),
            ]), run_id)
        self.render_messages()

    def failed(self, message):
        from .diagnostics import failure_message

        self.store.append(
            self.store.run(self.run_id)["session"],
            "assistant",
            failure_message(self.store, self.run_id),
        )
        self.status.setText("任务状态及处理建议已记录在对话中。")
        self.render_messages()

    def finished(self):
        self.worker.deleteLater()
        self.worker = None
        self.set_busy(False)
        self.refresh_balance()

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

    def connect_service(self):
        if self.worker:
            return False
        result = authenticate(self)
        if result is None:
            return False
        client, payload = result
        if client is None:
            return False
        if payload["owner"] != self.store.owner:
            self.store = (ProjectCatalog(self.store.index_path, payload["owner"])
                          if isinstance(self.store, ProjectCatalog)
                          else PlatformStore(self.store.path, payload["owner"]))
            self.project_id = self.session_id = self.run_id = None
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
        self.model_combo.clear()
        for model in self.models:
            self.model_combo.addItem(model["display_name"], model["model_id"])
        self.model_combo.show()
        self.balance_updated(payload["balance"]["balance"])
        self.connection_changed("connected")
        return True

    def cancel_run(self):
        if self.worker:
            self.worker.cancel.set()
            self.status.setText("已请求停止，等待当前文件解析结束。")
            self.stop.setEnabled(False)

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
        supported = "支持用户要求" if info["user_request_supported"] else "不兼容：缺少用户要求字段"
        self.version_label.setText(
            f"客户端 {CLIENT_VERSION} · Skill {REVIEW.version}\n"
            f"服务端 API {info['server_api_version']} · {supported}\n"
            "服务端构建号未提供（API 版本不等于部署版本）"
        )
        self.version_label.setToolTip(f"本地审核规则 SHA256：{local_release()['review_rules_sha256']}")

    def version_check_failed(self, _detail):
        self.version_label.setText(f"客户端 {CLIENT_VERSION} · 服务端版本检查失败，请检查网络后重试。")

    def version_check_finished(self):
        self.version_worker.wait()
        self.version_worker.deleteLater()
        self.version_worker = None

    def toggle_details(self):
        self.details.setVisible(not self.details.isVisible())

    def add_memory(self):
        if not self.project_id:
            return
        text, ok = QInputDialog.getText(
            self, "确认项目偏好", "该偏好只适用于当前项目："
        )
        if ok and text.strip():
            self.store.remember(self.project_id, text, confirmed=True)
            self.refresh_details()

    def delete_memory(self):
        item = self.memories.currentItem()
        if item and self.project_id:
            self.store.forget(self.project_id, item.data(Qt.ItemDataRole.UserRole))
            self.refresh_details()

    def archive(self):
        if self.worker or not self.project_id:
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
        if self.worker:
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
        if self.worker is not None:
            self.status.setText("请等待当前任务结束后管理 Skill。")
            return
        from .skill_manager import SkillManagerDialog

        SkillManagerDialog(self.store, self).exec()

    def claim_legacy_project(self):
        if isinstance(self.store, ProjectCatalog) and self.store.active is None:
            self.status.setText("请先打开包含旧数据的项目目录。")
            return
        if self.worker:
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
        if self.version_worker is not None:
            self.status.setText("版本检查尚未结束，请稍后关闭。")
            event.ignore()
            return
        if self.worker and self.worker.isRunning():
            self.cancel_run()
            event.ignore()
            return
        if self.monitor is not None:
            self.monitor.timer.stop()
            if self.monitor.worker is not None:
                self.status.setText("正在结束网络检查，请稍后关闭。")
                event.ignore()
                return
        event.accept()


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
    if args.data_dir is None:
        settings = Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppLocalDataLocation)) / "ZQPlatform"
        store = ProjectCatalog(settings / "project-locations.sqlite", payload["owner"])
    else:
        # Explicit legacy/test entry point; normal startup never creates business data here.
        store = PlatformStore(args.data_dir / "platform.sqlite", payload["owner"])
    window = PlatformWindow(
        store,
        client=client, models=payload["models"],
    )
    if client is not None:
        window.balance_updated(payload["balance"]["balance"])
    window.show()
    app.setQuitOnLastWindowClosed(True)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
