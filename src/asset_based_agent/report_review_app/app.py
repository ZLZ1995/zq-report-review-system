"""Desktop application composition root."""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from typing import Any, cast

from PySide6.QtCore import QTimer
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QMessageBox

from .branding import APPLICATION_NAME, application_icon_path
from .config import load_remote_client_settings, load_runtime_paths
from .repositories.project_repository import ProjectRepository
from .services.advice_service import AdviceService
from .services.audit_orchestrator import AuditOrchestrator
from .services.auth_service import AuthService
from .services.conversation_service import ConversationService
from .services.document_extraction_service import DocumentExtractionService
from .services.file_service import FileImportService
from .services.issue_service import IssueService
from .services.privacy_filter import PrivacyChunkSelector
from .services.project_service import ProjectService
from .services.remote_auth_service import (
    ConnectivitySupervisor,
    RemoteAuthenticationError,
    RemoteAuthService,
    RemoteSessionClient,
    WindowsCredentialStore,
    load_or_create_client_instance_id,
)
from .services.remote_review_llm import RemoteReviewLlm
from .services.report_export_service import ReportExportService
from .services.rule_registry import default_rule_registry
from .ui.login_window import LoginWindow
from .ui.project_window import ProjectWindow
from .ui.workbench_window import WorkbenchWindow


class DesktopController:
    def __init__(self, application: QApplication) -> None:
        self.application = application
        self.paths = load_runtime_paths()
        self.remote_settings = load_remote_client_settings()
        self.paths.app_data.mkdir(parents=True, exist_ok=True)
        self.remote_client: RemoteSessionClient | None = None
        if self.remote_settings.enabled:
            self.remote_client = RemoteSessionClient(
                self.remote_settings.server_url,
                client_instance_id=load_or_create_client_instance_id(
                    self.paths.client_instance
                ),
                credential_store=WindowsCredentialStore(),
            )
        self.repository = ProjectRepository(self.paths.projects_root)
        self.project_service = ProjectService(self.repository)
        self.file_service = FileImportService(self.repository)
        self.remote_models: list[dict[str, object]] = []
        self.remote_balance: dict[str, str] | None = None
        self.llm: Any
        if self.remote_client is not None:
            self.remote_review_llm = RemoteReviewLlm(self.remote_client)
            self.llm = self.remote_review_llm
        else:
            from .services.review_llm_client import OpenAICompatibleReviewLlm

            self.llm = OpenAICompatibleReviewLlm()
        self.orchestrator = AuditOrchestrator(
            self.repository,
            DocumentExtractionService(),
            default_rule_registry(),
            self.llm,
            PrivacyChunkSelector(),
        )
        self.issue_service = IssueService()
        self.advice_service = AdviceService(self.llm)
        self.conversation_service = ConversationService(self.llm)
        self.export_service = ReportExportService()
        self.session: dict[str, str] | None = None
        self.login_window: LoginWindow | None = None
        self.project_window: ProjectWindow | None = None
        self.workbench_window: WorkbenchWindow | None = None
        self.connectivity_supervisor: ConnectivitySupervisor | None = None
        self.connectivity_timer = QTimer(application)
        self.connectivity_timer.setInterval(1_000)
        self.connectivity_timer.timeout.connect(self._connectivity_tick)

    def start(self) -> None:
        self._show_login()

    def start_authenticated(self, session: dict[str, str]) -> None:
        self.session = session
        self._show_projects()

    def _show_login(self) -> None:
        self._close_window(self.project_window)
        self._close_window(self.workbench_window)
        self._stop_connectivity_monitor()
        self.session = None
        auth_service = (
            RemoteAuthService(self.remote_client)
            if self.remote_client is not None
            else AuthService(self.paths.user_config)
        )
        self.login_window = LoginWindow(auth_service)
        self.login_window.login_succeeded.connect(self._logged_in)
        self.login_window.show()

    def _logged_in(self, session: dict[str, str]) -> None:
        self.session = session
        self._close_window(self.login_window)
        if self.remote_client is not None:
            try:
                self.remote_models = self.remote_client.list_models()
                self.remote_balance = self.remote_client.get_balance()
                if not self.remote_models:
                    raise RemoteAuthenticationError("服务端没有可用审核模型。")
                first_model = self.remote_models[0].get("model_id")
                if not isinstance(first_model, str):
                    raise RemoteAuthenticationError("服务端模型配置无效。")
                self.remote_review_llm.set_model_id(first_model)
            except RemoteAuthenticationError as exc:
                QMessageBox.warning(None, "无法进入审核系统", str(exc))
                self._logout()
                return
            self._start_connectivity_monitor()
        self._show_projects()

    def _show_projects(self) -> None:
        if self.session is None:
            self._show_login()
            return
        self._close_window(self.workbench_window)
        self.project_window = ProjectWindow(
            self.project_service,
            self.session["display_name"],
        )
        self.project_window.project_selected.connect(self._open_project)
        self.project_window.logout_requested.connect(self._logout)
        self.project_window.show()

    def _open_project(self, project) -> None:
        if self.session is None:
            return
        self._close_window(self.project_window)
        self.workbench_window = WorkbenchWindow(
            project=project,
            username=self.session["username"],
            project_repository=self.repository,
            file_service=self.file_service,
            orchestrator=self.orchestrator,
            issue_service=self.issue_service,
            advice_service=self.advice_service,
            conversation_service=self.conversation_service,
            export_service=self.export_service,
            model_options=(
                [
                    (
                        str(item["model_id"]),
                        f"{item.get('display_name', item.get('code', '模型'))}"
                        f"（{item.get('tier', 'standard')}）",
                    )
                    for item in self.remote_models
                    if isinstance(item.get("model_id"), str)
                ]
                if self.remote_client is not None
                else None
            ),
            model_selected_callback=(
                self.remote_review_llm.set_model_id
                if self.remote_client is not None
                else None
            ),
            balance_display=(
                self.remote_balance.get("balance")
                if self.remote_balance is not None
                else None
            ),
        )
        self.workbench_window.back_requested.connect(self._show_projects)
        self.workbench_window.show()

    def _logout(self) -> None:
        if self.remote_client is not None:
            try:
                self.remote_client.logout()
            except RemoteAuthenticationError:
                pass
        self._show_login()

    def _start_connectivity_monitor(self) -> None:
        if self.remote_client is None:
            return
        self.connectivity_supervisor = ConnectivitySupervisor(
            self.remote_client.heartbeat,
            checkpoint=self._save_network_checkpoint,
            force_exit=self._force_network_exit,
        )
        self.connectivity_timer.start()

    def _stop_connectivity_monitor(self) -> None:
        self.connectivity_timer.stop()
        self.connectivity_supervisor = None

    def _connectivity_tick(self) -> None:
        if self.connectivity_supervisor is None:
            return
        state = self.connectivity_supervisor.tick()
        message = ""
        if state == "reconnecting":
            message = "网络连接中断，正在重连；30秒内未恢复将自动退出。"
        for window in (self.project_window, self.workbench_window):
            if window is not None:
                window.statusBar().showMessage(message)

    def _save_network_checkpoint(self) -> None:
        project = getattr(self.workbench_window, "project", None)
        payload = {
            "saved_at": datetime.now(timezone.utc).isoformat(),
            "reason": "network_timeout_or_session_revoked",
            "project_id": getattr(project, "project_id", None),
        }
        destination = self.paths.app_data / "network-exit-checkpoint.json"
        temporary = destination.with_suffix(destination.suffix + ".tmp")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        os.replace(temporary, destination)

    def _force_network_exit(self) -> None:
        self.connectivity_timer.stop()
        self._close_window(self.login_window)
        self._close_window(self.project_window)
        self._close_window(self.workbench_window)
        self.application.quit()

    @staticmethod
    def _close_window(window) -> None:
        if window is not None:
            window.close()
            window.deleteLater()


_DESKTOP_STYLE = (
    "QMainWindow { background: #f5f7fa; }"
    "QPushButton { padding: 7px 14px; }"
    "QPushButton#dangerButton { color: #b42318; border: 1px solid #fda29b; }"
    "QPushButton#dangerButton:hover { background: #fef3f2; }"
    "QPushButton#dangerButton:disabled { color: #98a2b3; border-color: #d0d5dd; }"
    "QTableWidget { background: white; gridline-color: #d9e0e8; }"
)


def apply_desktop_style(application: QApplication) -> None:
    application.setStyleSheet(
        _DESKTOP_STYLE
    )


def main() -> int:
    application = cast(QApplication | None, QApplication.instance()) or QApplication(
        sys.argv
    )
    application.setApplicationName(APPLICATION_NAME)
    application.setWindowIcon(QIcon(str(application_icon_path())))
    apply_desktop_style(application)
    controller = DesktopController(application)
    controller.start()
    return application.exec()


if __name__ == "__main__":
    raise SystemExit(main())
