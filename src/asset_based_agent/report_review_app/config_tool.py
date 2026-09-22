"""Standalone local account and API configuration tool."""

from __future__ import annotations

import sys
from collections.abc import Callable
from typing import Protocol, cast

from PySide6.QtCore import QObject, QSignalBlocker, Qt, QThread, Signal, Slot
from PySide6.QtGui import QCloseEvent, QIcon
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFrame,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPushButton,
    QScrollArea,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .branding import APPLICATION_NAME, CONFIG_TOOL_NAME, application_icon_path
from .config import load_runtime_paths
from .services.auth_service import (
    AuthConfigurationError,
    AuthenticationError,
    AuthService,
)
from .services.setup_service import (
    ModelDiscoveryError,
    ReportReviewSetupService,
    SetupValidationError,
)


class _AuthenticatedDesktopController(Protocol):
    def start_authenticated(self, session: dict[str, str]) -> None:
        ...


DesktopControllerFactory = Callable[
    [QApplication],
    _AuthenticatedDesktopController,
]


def _default_desktop_controller_factory(
    application: QApplication,
) -> _AuthenticatedDesktopController:
    from .app import DesktopController, apply_desktop_style

    apply_desktop_style(application)
    return DesktopController(application)


class _ModelDiscoveryWorker(QObject):
    succeeded = Signal(object)
    failed = Signal(str)
    progress = Signal(int, int)

    def __init__(
        self,
        service: ReportReviewSetupService,
        *,
        api_base: str,
        api_key: str,
        provider: str,
    ) -> None:
        super().__init__()
        self.service = service
        self.api_base = api_base
        self.api_key = api_key
        self.provider = provider

    @Slot()
    def run(self) -> None:
        try:
            models = self.service.discover_models(
                api_base=self.api_base,
                api_key=self.api_key,
                provider=self.provider,
                progress_callback=self.progress.emit,
            )
        except (ModelDiscoveryError, SetupValidationError) as exc:
            self.failed.emit(str(exc))
            return
        except Exception as exc:
            self.failed.emit(
                f"连接测试发生内部错误（{type(exc).__name__}），请重新启动后再试。"
            )
            return
        self.succeeded.emit(models)


class ConfigToolWindow(QMainWindow):
    def __init__(
        self,
        setup_service: ReportReviewSetupService | None = None,
        desktop_controller_factory: DesktopControllerFactory | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._api_form_loading = True
        self._testing_connection = False
        self._api_key_configured = False
        self._saved_model = ""
        self._model_thread: QThread | None = None
        self._model_worker: _ModelDiscoveryWorker | None = None
        self._model_result: tuple[bool, object] | None = None
        self._close_requested = False
        self.desktop_controller_factory = (
            desktop_controller_factory or _default_desktop_controller_factory
        )
        self.desktop_controller: _AuthenticatedDesktopController | None = None
        paths = load_runtime_paths()
        self.setup_service = setup_service or ReportReviewSetupService(
            users_path=paths.user_config,
        )
        self.setWindowTitle(CONFIG_TOOL_NAME)
        self.setMinimumSize(760, 680)
        self.resize(860, 760)
        self._build_ui()
        self._load_api_status()
        self._api_form_loading = False
        self._update_api_actions()

    def _build_ui(self) -> None:
        root = QWidget()
        layout = QVBoxLayout(root)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(14)

        title = QLabel(APPLICATION_NAME)
        title.setObjectName("title")
        subtitle = QLabel("本地账号与模型 API 配置")
        subtitle.setObjectName("subtitle")
        layout.addWidget(title)
        layout.addWidget(subtitle)

        notice = QLabel(
            "所有设置仅保存在本机。账号密码以 PBKDF2 哈希保存；"
            "API Key 按主程序现有配置格式保存在当前 Windows 用户目录中。"
        )
        notice.setWordWrap(True)
        notice.setObjectName("notice")
        layout.addWidget(notice)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_account_tab(), "账号配置")
        self.tabs.addTab(self._build_api_tab(), "API 配置")
        layout.addWidget(self.tabs, 1)
        self.setCentralWidget(root)

    def _build_account_tab(self) -> QWidget:
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(28, 28, 28, 28)
        layout.setSpacing(18)

        description = QLabel(
            "创建新账号，或输入已有用户名更新显示名称和密码。其他账号不会被删除。"
        )
        description.setWordWrap(True)
        description.setObjectName("sectionDescription")
        layout.addWidget(description)

        heading = QLabel("账号信息")
        heading.setObjectName("sectionTitle")
        layout.addWidget(heading)

        self.account_username_input = QLineEdit()
        self.account_username_input.setPlaceholderText("例如：reviewer")
        self.account_display_name_input = QLineEdit()
        self.account_display_name_input.setPlaceholderText("选填")
        self.account_password_input = QLineEdit()
        self.account_password_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.account_password_input.setPlaceholderText("至少 8 个字符")
        self.account_confirmation_input = QLineEdit()
        self.account_confirmation_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.account_confirmation_input.setPlaceholderText("再次输入密码")
        self._add_labeled_field(layout, "用户名", self.account_username_input)
        self._add_labeled_field(
            layout,
            "显示名称（选填）",
            self.account_display_name_input,
        )
        self._add_labeled_field(layout, "密码", self.account_password_input)
        self._add_labeled_field(
            layout,
            "确认密码",
            self.account_confirmation_input,
        )

        show_password = QCheckBox("显示密码")
        show_password.toggled.connect(self._toggle_account_passwords)
        layout.addWidget(show_password)

        self.account_status_label = QLabel()
        self.account_status_label.setWordWrap(True)
        self.account_status_label.setMinimumHeight(32)
        layout.addWidget(self.account_status_label)

        self.account_save_button = QPushButton("保存账号")
        self.account_save_button.setObjectName("secondaryButton")
        self.account_save_button.clicked.connect(self._save_account)
        layout.addWidget(self.account_save_button, alignment=Qt.AlignmentFlag.AlignLeft)

        divider = QFrame()
        divider.setObjectName("divider")
        divider.setFrameShape(QFrame.Shape.HLine)
        layout.addWidget(divider)

        login_heading = QLabel("进入审核系统")
        login_heading.setObjectName("sectionTitle")
        layout.addWidget(login_heading)
        login_description = QLabel(
            "账号及 API 配置完成后，使用上方用户名和密码登录主程序。"
        )
        login_description.setObjectName("sectionDescription")
        login_description.setWordWrap(True)
        layout.addWidget(login_description)

        self.login_button = QPushButton("登录并进入报告审核系统")
        self.login_button.setObjectName("primaryButton")
        self.login_button.clicked.connect(self._login_and_open_main)
        layout.addWidget(self.login_button, alignment=Qt.AlignmentFlag.AlignLeft)

        self.account_username_input.textChanged.connect(
            self._update_login_action
        )
        self.account_password_input.textChanged.connect(
            self._update_login_action
        )
        self.account_password_input.returnPressed.connect(
            self._login_and_open_main
        )
        layout.addStretch(1)
        return self._as_scroll_area(content)

    def _build_api_tab(self) -> QWidget:
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(28, 28, 28, 28)
        layout.setSpacing(18)

        description = QLabel(
            "录入 OpenAI-compatible API。已有 API Key 不会回显；"
            "修改其他字段时可将密钥留空以保留原值。"
        )
        description.setWordWrap(True)
        description.setObjectName("sectionDescription")
        layout.addWidget(description)

        connection_heading = QLabel("连接信息")
        connection_heading.setObjectName("sectionTitle")
        layout.addWidget(connection_heading)

        self.api_base_input = QLineEdit()
        self.api_base_input.setPlaceholderText("https://api.example.com")
        self.api_key_input = QLineEdit()
        self.api_key_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.api_key_input.setPlaceholderText("首次配置必须填写")
        self._add_labeled_field(layout, "API 地址", self.api_base_input)
        self._add_labeled_field(layout, "API Key", self.api_key_input)

        show_key = QCheckBox("显示 API Key")
        show_key.toggled.connect(self._toggle_api_key)
        layout.addWidget(show_key)

        self.api_test_button = QPushButton("测试连接并获取模型")
        self.api_test_button.setObjectName("secondaryButton")
        layout.addWidget(
            self.api_test_button,
            alignment=Qt.AlignmentFlag.AlignLeft,
        )

        self.api_status_label = QLabel()
        self.api_status_label.setWordWrap(True)
        self.api_status_label.setMinimumHeight(44)
        layout.addWidget(self.api_status_label)

        divider = QFrame()
        divider.setObjectName("divider")
        divider.setFrameShape(QFrame.Shape.HLine)
        layout.addWidget(divider)

        model_heading = QLabel("模型与调用方式")
        model_heading.setObjectName("sectionTitle")
        layout.addWidget(model_heading)

        self.api_model_input = QComboBox()
        self.api_model_input.setEditable(False)
        self.api_model_input.setPlaceholderText("请先测试连接并选择模型")
        self.api_provider_input = QComboBox()
        self.api_provider_input.addItem(
            "OpenAI-compatible（兼容服务）",
            "openai-compatible",
        )
        self.api_provider_input.addItem("DeepSeek 官方 API", "deepseek")
        self.api_wire_input = QComboBox()
        self.api_wire_input.addItems(["chat_completions", "responses"])
        self._add_labeled_field(layout, "模型名称", self.api_model_input)
        self._add_labeled_field(layout, "服务类型", self.api_provider_input)
        self._add_labeled_field(layout, "接口类型", self.api_wire_input)

        self.api_save_button = QPushButton("保存 API 配置")
        self.api_save_button.setObjectName("primaryButton")
        self.api_save_button.clicked.connect(self._save_api)
        layout.addWidget(self.api_save_button, alignment=Qt.AlignmentFlag.AlignLeft)
        layout.addStretch(1)

        self.api_base_input.textChanged.connect(
            self._on_connection_input_changed
        )
        self.api_key_input.textChanged.connect(
            self._on_connection_input_changed
        )
        self.api_model_input.currentIndexChanged.connect(
            self._update_api_actions
        )
        self.api_provider_input.currentIndexChanged.connect(
            self._provider_changed
        )
        self.api_test_button.clicked.connect(self._test_connection)
        return self._as_scroll_area(content)

    @staticmethod
    def _add_labeled_field(
        layout: QVBoxLayout,
        label_text: str,
        control: QWidget,
    ) -> None:
        field = QWidget()
        field_layout = QVBoxLayout(field)
        field_layout.setContentsMargins(0, 0, 0, 0)
        field_layout.setSpacing(7)
        label = QLabel(label_text)
        label.setObjectName("fieldLabel")
        control.setMinimumHeight(42)
        field_layout.addWidget(label)
        field_layout.addWidget(control)
        layout.addWidget(field)

    @staticmethod
    def _as_scroll_area(content: QWidget) -> QScrollArea:
        scroll = QScrollArea()
        scroll.setObjectName("tabScrollArea")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        scroll.setWidget(content)
        return scroll

    def _load_api_status(self) -> None:
        try:
            status = self.setup_service.load_api_config_status()
        except SetupValidationError as exc:
            self._set_status(self.api_status_label, str(exc), success=False)
            return
        self._api_key_configured = status.api_key_configured
        self._saved_model = status.model
        self.api_base_input.setText(status.api_base)
        provider_index = self.api_provider_input.findData(status.provider)
        self.api_provider_input.setCurrentIndex(
            max(provider_index, 0)
        )
        self.api_wire_input.setCurrentText(status.wire_api)
        self.api_wire_input.setEnabled(status.provider != "deepseek")
        if status.model:
            self.api_model_input.addItem(status.model)
            self.api_model_input.setCurrentIndex(0)
        else:
            self.api_model_input.setCurrentIndex(-1)
        if status.api_key_configured:
            self.api_key_input.setPlaceholderText("已配置；留空将保留原 API Key")
            self._set_status(
                self.api_status_label,
                "已检测到现有 API Key，可直接修改其他配置。",
                success=True,
            )

    def _save_account(self) -> None:
        try:
            path = self.setup_service.create_or_update_account(
                username=self.account_username_input.text(),
                display_name=self.account_display_name_input.text(),
                password=self.account_password_input.text(),
                confirmation=self.account_confirmation_input.text(),
            )
        except SetupValidationError as exc:
            self._set_status(self.account_status_label, str(exc), success=False)
            return
        self.account_confirmation_input.clear()
        self._set_status(
            self.account_status_label,
            f"账号保存成功：{path}",
            success=True,
        )
        self._update_login_action()

    def _save_api(self) -> None:
        try:
            path = self._persist_api_config()
        except SetupValidationError as exc:
            self._set_status(self.api_status_label, str(exc), success=False)
            return
        self._api_config_saved(path)

    def _persist_api_config(self):
        return self.setup_service.save_api_config(
            api_base=self.api_base_input.text(),
            api_key=self.api_key_input.text(),
            model=self.api_model_input.currentText(),
            provider=str(self.api_provider_input.currentData()),
            wire_api=self.api_wire_input.currentText(),
        )

    def _api_config_saved(self, path) -> None:
        self._api_key_configured = True
        self._saved_model = self.api_model_input.currentText()
        with QSignalBlocker(self.api_key_input):
            self.api_key_input.clear()
        self.api_key_input.setPlaceholderText("已配置；留空将保留原 API Key")
        self._set_status(
            self.api_status_label,
            f"API 配置保存成功：{path}",
            success=True,
        )
        self._update_api_actions()

    @Slot()
    def _login_and_open_main(self) -> None:
        if not self._login_requirements_ready():
            self._set_status(
                self.account_status_label,
                "请先完成账号、API 地址、API Key 和模型选择。",
                success=False,
            )
            return
        try:
            session = AuthService(self.setup_service.users_path).authenticate(
                self.account_username_input.text(),
                self.account_password_input.text(),
            )
        except AuthenticationError:
            self._set_status(
                self.account_status_label,
                "用户名或密码错误。",
                success=False,
            )
            return
        except AuthConfigurationError:
            self._set_status(
                self.account_status_label,
                "账号配置不存在或无法读取，请先保存账号。",
                success=False,
            )
            return
        try:
            path = self._persist_api_config()
        except SetupValidationError as exc:
            self._set_status(
                self.account_status_label,
                f"API 配置无效：{exc}",
                success=False,
            )
            return

        application = cast(QApplication | None, QApplication.instance())
        if application is None:
            self._set_status(
                self.account_status_label,
                "无法取得桌面应用实例，请重新启动配置工具。",
                success=False,
            )
            return
        try:
            controller = self.desktop_controller_factory(application)
            controller.start_authenticated(session)
        except Exception as exc:
            self._set_status(
                self.account_status_label,
                f"主程序启动失败（{type(exc).__name__}），请重新启动后再试。",
                success=False,
            )
            return

        self.desktop_controller = controller
        self._api_config_saved(path)
        self.account_password_input.clear()
        self.account_confirmation_input.clear()
        self.hide()

    @Slot()
    def _on_connection_input_changed(self) -> None:
        if self._api_form_loading or self._testing_connection:
            return
        self.api_model_input.clear()
        self.api_model_input.setCurrentIndex(-1)
        self._update_api_actions()

    @Slot()
    def _provider_changed(self) -> None:
        if self._api_form_loading:
            return
        provider = str(self.api_provider_input.currentData())
        if provider == "deepseek":
            self.api_base_input.setText("https://api.deepseek.com")
            self.api_wire_input.setCurrentText("chat_completions")
            self.api_wire_input.setEnabled(False)
        else:
            self.api_wire_input.setEnabled(True)
        self._update_api_actions()

    @Slot()
    def _update_api_actions(self) -> None:
        has_base = bool(self.api_base_input.text().strip())
        has_key = bool(self.api_key_input.text().strip()) or self._api_key_configured
        self.api_test_button.setEnabled(
            has_base and has_key and not self._testing_connection
        )
        self.api_save_button.setEnabled(
            self.api_model_input.currentIndex() >= 0
            and not self._testing_connection
        )
        self._update_login_action()

    @Slot()
    def _update_login_action(self) -> None:
        self.login_button.setEnabled(self._login_requirements_ready())

    def _login_requirements_ready(self) -> bool:
        has_key = bool(self.api_key_input.text().strip()) or self._api_key_configured
        return (
            bool(self.account_username_input.text().strip())
            and bool(self.account_password_input.text())
            and bool(self.api_base_input.text().strip())
            and has_key
            and self.api_model_input.currentIndex() >= 0
            and not self._testing_connection
        )

    @Slot()
    def _test_connection(self) -> None:
        if self._testing_connection or self._model_thread is not None or self._close_requested:
            return
        self._model_result = None
        self._testing_connection = True
        self.api_base_input.setEnabled(False)
        self.api_key_input.setEnabled(False)
        self.api_model_input.clear()
        self.api_model_input.setCurrentIndex(-1)
        self.api_test_button.setText("正在连接…")
        self._set_status(
            self.api_status_label,
            "正在连接模型服务并获取模型列表…",
            success=True,
        )
        self._update_api_actions()

        thread = QThread(self)
        worker = _ModelDiscoveryWorker(
            self.setup_service,
            api_base=self.api_base_input.text(),
            api_key=self.api_key_input.text(),
            provider=str(self.api_provider_input.currentData()),
        )
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.succeeded.connect(self._model_discovery_succeeded)
        worker.failed.connect(self._model_discovery_failed)
        worker.progress.connect(self._model_discovery_progress)
        # QThread.quit is thread-safe; do not depend on a GUI event to stop it.
        worker.succeeded.connect(thread.quit, Qt.ConnectionType.DirectConnection)
        worker.failed.connect(thread.quit, Qt.ConnectionType.DirectConnection)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(self._model_thread_finished)
        self._model_thread = thread
        self._model_worker = worker
        thread.start()

    @Slot(int, int)
    def _model_discovery_progress(self, attempt: int, total: int) -> None:
        self.api_test_button.setText(f"正在连接（{attempt}/{total}）…")
        self._set_status(
            self.api_status_label,
            f"正在连接模型服务并获取模型列表（第 {attempt}/{total} 次）…",
            success=True,
        )

    @Slot(object)
    def _model_discovery_succeeded(self, models: object) -> None:
        self._model_result = (True, models)

    @Slot(str)
    def _model_discovery_failed(self, message: str) -> None:
        self._model_result = (False, message)

    def _finish_model_discovery(self) -> None:
        self._testing_connection = False
        self.api_base_input.setEnabled(True)
        self.api_key_input.setEnabled(True)
        self.api_test_button.setText("测试连接并获取模型")
        self._update_api_actions()

    def _apply_discovered_models(self, models: list[str]) -> None:
        self.api_model_input.clear()
        self.api_model_input.addItems(models)
        saved_index = self.api_model_input.findText(self._saved_model)
        self.api_model_input.setCurrentIndex(saved_index)
        self._update_api_actions()

    @Slot()
    def _model_thread_finished(self) -> None:
        if self._model_thread is not None:
            # finished precedes native thread-local cleanup; join before release.
            self._model_thread.wait()
            self._model_thread.deleteLater()
        self._model_thread = None
        self._model_worker = None
        result, self._model_result = self._model_result, None
        self._finish_model_discovery()
        if self._close_requested:
            self.close()
            return
        if result is not None and result[0]:
            self._apply_discovered_models(list(cast(list[str], result[1])))
            self._set_status(
                self.api_status_label,
                f"连接成功，共获取 {self.api_model_input.count()} 个模型，请选择使用模型。",
                success=True,
            )
        else:
            self.api_model_input.clear()
            self.api_model_input.setCurrentIndex(-1)
            self._set_status(
                self.api_status_label,
                str(result[1]) if result is not None else "连接未返回结果，请重试。",
                success=False,
            )

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._model_thread is not None:
            self._close_requested = True
            self._set_status(self.api_status_label, "正在等待连接结束，随后自动关闭。", success=True)
            event.ignore()
            return
        super().closeEvent(event)

    def _toggle_account_passwords(self, visible: bool) -> None:
        mode = (
            QLineEdit.EchoMode.Normal
            if visible
            else QLineEdit.EchoMode.Password
        )
        self.account_password_input.setEchoMode(mode)
        self.account_confirmation_input.setEchoMode(mode)

    def _toggle_api_key(self, visible: bool) -> None:
        self.api_key_input.setEchoMode(
            QLineEdit.EchoMode.Normal
            if visible
            else QLineEdit.EchoMode.Password
        )

    @staticmethod
    def _set_status(label: QLabel, text: str, *, success: bool) -> None:
        color = "#166534" if success else "#b42318"
        label.setStyleSheet(f"color: {color}; font-weight: 600;")
        label.setText(text)


_STYLE = """
QMainWindow, QWidget {
    background: #f6f8fb;
    color: #243447;
    font-size: 14px;
}
QLabel#title {
    font-size: 24px;
    font-weight: 700;
    color: #172b4d;
}
QLabel#subtitle {
    font-size: 16px;
    color: #5e6c84;
}
QLabel#notice {
    background: #eaf2ff;
    border: 1px solid #b8d4ff;
    border-radius: 8px;
    padding: 10px;
    color: #174ea6;
}
QLabel#sectionTitle {
    font-size: 16px;
    font-weight: 700;
    color: #172b4d;
    margin-top: 4px;
}
QLabel#sectionDescription {
    color: #475569;
}
QLabel#fieldLabel {
    color: #334155;
    font-weight: 600;
}
QFrame#divider {
    color: #d9e2ec;
    margin: 4px 0;
}
QScrollArea#tabScrollArea,
QScrollArea#tabScrollArea > QWidget > QWidget {
    background: white;
}
QTabWidget::pane {
    background: white;
    border: 1px solid #d9e2ec;
    border-radius: 8px;
}
QTabBar::tab {
    background: #e9eef5;
    padding: 10px 22px;
    margin-right: 3px;
}
QTabBar::tab:selected {
    background: white;
    color: #175cd3;
    font-weight: 600;
}
QLineEdit, QComboBox {
    min-height: 40px;
    background: white;
    border: 1px solid #cbd5e1;
    border-radius: 6px;
    padding: 0 12px;
}
QLineEdit:focus, QComboBox:focus {
    border: 1px solid #2f6fed;
}
QPushButton#primaryButton {
    background: #175cd3;
    color: white;
    border: none;
    border-radius: 6px;
    min-height: 42px;
    padding: 0 22px;
    font-weight: 600;
}
QPushButton#primaryButton:hover {
    background: #124ca6;
}
QPushButton#secondaryButton {
    background: white;
    color: #175cd3;
    border: 1px solid #175cd3;
    border-radius: 6px;
    min-height: 42px;
    padding: 0 20px;
    font-weight: 600;
}
QPushButton#secondaryButton:hover {
    background: #eef4ff;
}
QPushButton#primaryButton:disabled,
QPushButton#secondaryButton:disabled {
    background: #e5e7eb;
    color: #9ca3af;
    border: 1px solid #d1d5db;
}
"""


def main() -> int:
    application = cast(QApplication | None, QApplication.instance()) or QApplication(
        sys.argv
    )
    application.setApplicationName(CONFIG_TOOL_NAME)
    application.setWindowIcon(QIcon(str(application_icon_path())))
    application.setStyleSheet(_STYLE)
    window = ConfigToolWindow()
    window.show()
    return application.exec()


if __name__ == "__main__":
    raise SystemExit(main())
