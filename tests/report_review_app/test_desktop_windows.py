from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox

from asset_based_agent.report_review_app.app import (
    DesktopController,
    apply_desktop_style,
)
from asset_based_agent.report_review_app.domain.enums import ProjectStatus, RoundStatus
from asset_based_agent.report_review_app.domain.models import AuditRound
from asset_based_agent.report_review_app.repositories.issue_repository import (
    IssueRepository,
)
from asset_based_agent.report_review_app.repositories.project_repository import (
    ProjectRepository,
)
from asset_based_agent.report_review_app.services.advice_service import AdviceService
from asset_based_agent.report_review_app.services.agent_gateway import (
    AdviceResult,
    ConversationTurnResult,
)
from asset_based_agent.report_review_app.services.audit_orchestrator import AuditOrchestrator
from asset_based_agent.report_review_app.services.auth_service import (
    AuthService,
    write_user_config,
)
from asset_based_agent.report_review_app.services.conversation_service import (
    ConversationService,
)
from asset_based_agent.report_review_app.services.document_extraction_service import (
    DocumentExtractionService,
)
from asset_based_agent.report_review_app.services.file_service import FileImportService
from asset_based_agent.report_review_app.services.issue_service import IssueService
from asset_based_agent.report_review_app.services.project_service import ProjectService
from asset_based_agent.report_review_app.services.report_export_service import (
    ReportExportService,
)
from asset_based_agent.report_review_app.services.review_llm_client import NoOpReviewLlm
from asset_based_agent.report_review_app.services.rule_registry import RuleRegistry
from asset_based_agent.report_review_app.ui.login_window import LoginWindow
from asset_based_agent.report_review_app.ui.project_window import ProjectWindow
from asset_based_agent.report_review_app.ui.workbench_window import (
    WorkbenchWindow,
    _format_audit_error,
    _format_progress_detail,
)


class FakeAdvice:
    def generate_advice(self, request):
        return AdviceResult(issue_id=request.issue.issue_id, explanation="advice")

    def continue_conversation(self, request):
        return ConversationTurnResult(reply="conversation reply")


class RecordingExport:
    def __init__(self) -> None:
        self.destination: Path | None = None

    def export(self, project, destination):
        self.destination = Path(destination)
        self.destination.parent.mkdir(parents=True, exist_ok=True)
        self.destination.write_bytes(b"report")
        summary = self.destination.with_suffix(".summary.json")
        summary.write_text("{}", encoding="utf-8")
        return summary, self.destination


def application() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_login_window_emits_session_for_valid_local_credentials(
    tmp_path: Path,
) -> None:
    application()
    config = tmp_path / "users.json"
    write_user_config(config, username="reviewer", password="password")
    window = LoginWindow(AuthService(config))
    sessions = []
    window.login_succeeded.connect(sessions.append)
    window.username_input.setText("reviewer")
    window.password_input.setText("password")

    window.login_button.click()

    assert sessions[0]["username"] == "reviewer"


def test_login_window_runs_remote_authentication_in_worker() -> None:
    application()

    class RemoteAuth:
        is_remote = True

        def authenticate(self, username: str, password: str) -> dict[str, str]:
            return {"username": username, "display_name": "Remote Reviewer"}

    window = LoginWindow(RemoteAuth())
    sessions: list[dict[str, str]] = []
    window.login_succeeded.connect(sessions.append)
    window.username_input.setText("reviewer")
    window.password_input.setText("Password123!")

    window.login_button.click()

    assert window.login_worker is not None
    assert window.login_worker.wait(2_000)
    application().processEvents()
    assert sessions[0]["username"] == "reviewer"
    assert window.password_input.text() == ""
    assert window.login_button.isEnabled()


def test_remote_login_failure_does_not_expose_internal_error() -> None:
    application()

    class RemoteAuth:
        is_remote = True

        def authenticate(self, username: str, password: str) -> dict[str, str]:
            raise RuntimeError("https://secret-relay.invalid?key=SECRET")

    window = LoginWindow(RemoteAuth())
    window.username_input.setText("reviewer")
    window.password_input.setText("Password123!")
    window.login_button.click()
    assert window.login_worker is not None
    assert window.login_worker.wait(2_000)
    application().processEvents()

    assert "SECRET" not in window.error_label.text()
    assert "invalid" not in window.error_label.text()
    assert window.password_input.text() == ""


def test_workbench_disables_audit_before_upload(tmp_path: Path) -> None:
    application()
    repository = ProjectRepository(tmp_path / "projects")
    project = repository.create("project")
    window = WorkbenchWindow(
        project=project,
        username="reviewer",
        project_repository=repository,
        file_service=FileImportService(repository),
        orchestrator=AuditOrchestrator(
            repository,
            DocumentExtractionService(),
            RuleRegistry(),
            NoOpReviewLlm(),
        ),
        issue_service=IssueService(),
        advice_service=AdviceService(FakeAdvice()),
        conversation_service=ConversationService(FakeAdvice()),
        export_service=ReportExportService(),
    )

    assert window.audit_button.isEnabled() is False
    assert window.replace_button.isVisibleTo(window) is False


def test_workbench_file_list_can_be_collapsed_and_expanded(tmp_path: Path) -> None:
    application()
    repository = ProjectRepository(tmp_path / "projects")
    project = repository.create("project")
    window = _workbench(repository, project, ReportExportService())

    assert window.file_table.isHidden() is False
    assert window.files_toggle_button.text() == "文件列表（0）"

    window.files_toggle_button.click()

    assert window.file_table.isHidden() is True

    window.files_toggle_button.click()

    assert window.file_table.isHidden() is False


def test_workbench_model_selector_changes_remote_model(tmp_path: Path) -> None:
    application()
    repository = ProjectRepository(tmp_path / "projects")
    project = repository.create("project")
    selected: list[str] = []
    window = _workbench(
        repository,
        project,
        ReportExportService(),
        model_options=[("MODEL-1", "DeepSeek"), ("MODEL-2", "Relay")],
        model_selected_callback=selected.append,
    )

    assert window.model_combo is not None
    window.model_combo.setCurrentIndex(1)

    assert selected == ["MODEL-2"]


def test_desktop_controller_can_start_with_authenticated_session() -> None:
    controller = DesktopController.__new__(DesktopController)
    controller.session = None
    calls: list[bool] = []
    controller._show_projects = lambda: calls.append(True)
    session = {"username": "reviewer", "display_name": "Review User"}

    controller.start_authenticated(session)

    assert controller.session == session
    assert calls == [True]


def test_applying_desktop_style_replaces_config_tool_style() -> None:
    app = application()
    app.setStyleSheet("QLabel#title { color: red; }")

    apply_desktop_style(app)

    assert "QTableWidget" in app.styleSheet()
    assert "QLabel#title" not in app.styleSheet()


def test_project_window_delete_requires_selection_and_refreshes_list(
    tmp_path: Path,
    monkeypatch,
) -> None:
    application()
    repository = ProjectRepository(tmp_path / "projects")
    project = repository.create("待删除项目")
    window = ProjectWindow(ProjectService(repository), "reviewer")
    messages: list[str] = []
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *_args, **_kwargs: QMessageBox.StandardButton.Yes,
    )
    monkeypatch.setattr(
        QMessageBox,
        "information",
        lambda _parent, _title, message, *_args, **_kwargs: messages.append(message),
    )

    assert window.delete_button.isEnabled() is False
    window.project_list.setCurrentRow(0)
    assert window.delete_button.isEnabled() is True

    window.delete_button.click()

    assert repository.list() == []
    assert window.project_list.count() == 0
    assert not Path(project.project_path).exists()
    assert messages


def test_project_window_cancel_delete_keeps_project(
    tmp_path: Path,
    monkeypatch,
) -> None:
    application()
    repository = ProjectRepository(tmp_path / "projects")
    project = repository.create("保留项目")
    window = ProjectWindow(ProjectService(repository), "reviewer")
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *_args, **_kwargs: QMessageBox.StandardButton.No,
    )
    window.project_list.setCurrentRow(0)

    window.delete_button.click()

    assert repository.get(project.project_id).name == "保留项目"
    assert window.project_list.count() == 1


def test_schema_error_is_presented_as_actionable_chinese_message() -> None:
    message = _format_audit_error(
        "ReviewResponseSchemaError: LLM review response failed schema validation: "
        "issues.0.evidence_summaries.0: invalid value"
    )

    assert "模型已经成功返回结果" in message
    assert "上传文件未被修改" in message
    assert "pydantic" not in message.lower()
    assert "issues.0" not in message


def test_network_error_is_presented_without_internal_exception_text() -> None:
    message = _format_audit_error(
        "ReviewNetworkError: LLM network request failed: IncompleteRead(0 bytes read)"
    )

    assert "模型服务的响应在传输过程中中断" in message
    assert "自动重试" in message
    assert "上传文件未被修改" in message
    assert "继续未完成审核" in message
    assert "ReviewNetworkError" not in message
    assert "IncompleteRead" not in message


def test_progress_detail_explains_batch_retry_and_elapsed_time() -> None:
    detail = _format_progress_detail(
        {
            "detail": "模型响应中断，正在自动重试",
            "batch_index": 2,
            "batch_total": 5,
            "attempt": 2,
            "attempt_total": 3,
        },
        elapsed_seconds=65,
    )

    assert detail == (
        "模型响应中断，正在自动重试"
        " · 第 2/5 批"
        " · 第 2/3 次尝试"
        " · 已用时 01:05"
    )


def test_finish_project_exports_to_user_selected_path(
    tmp_path: Path,
    monkeypatch,
) -> None:
    application()
    repository, project = _completed_project(tmp_path)
    export_service = RecordingExport()
    window = _workbench(repository, project, export_service)
    selected_path = tmp_path / "selected-by-user" / "审核意见.docx"
    monkeypatch.setattr(
        QFileDialog,
        "getSaveFileName",
        lambda *_args, **_kwargs: (str(selected_path), "Word 文档 (*.docx)"),
    )
    monkeypatch.setattr(QMessageBox, "information", lambda *_args, **_kwargs: None)

    window._finish_project()

    saved = repository.get(project.project_id)
    assert export_service.destination == selected_path
    assert saved.status == ProjectStatus.COMPLETED
    assert saved.final_report_path == str(selected_path)


def test_finish_project_cancel_does_not_export_or_complete(
    tmp_path: Path,
    monkeypatch,
) -> None:
    application()
    repository, project = _completed_project(tmp_path)
    export_service = RecordingExport()
    window = _workbench(repository, project, export_service)
    monkeypatch.setattr(
        QFileDialog,
        "getSaveFileName",
        lambda *_args, **_kwargs: ("", ""),
    )

    window._finish_project()

    saved = repository.get(project.project_id)
    assert export_service.destination is None
    assert saved.status == ProjectStatus.READY
    assert saved.final_report_path is None


def _completed_project(tmp_path: Path):
    repository = ProjectRepository(tmp_path / "projects")
    project = repository.create("project")
    round_dir = Path(project.project_path) / "rounds" / "round-001"
    issues_path = round_dir / "issues.json"
    IssueRepository().save_issues(
        issues_path,
        project_id=project.project_id,
        round_number=1,
        issues=[],
    )
    project.current_round = 1
    project.status = ProjectStatus.READY
    project.rounds.append(
        AuditRound(
            round_id="ROUND-1",
            round_number=1,
            status=RoundStatus.COMPLETED,
            progress_path=str(round_dir / "progress.json"),
            issues_path=str(issues_path),
            error_snapshot_path=str(round_dir / "error_snapshot.json"),
        )
    )
    repository.save(project)
    return repository, project


def _workbench(repository, project, export_service, **kwargs):
    return WorkbenchWindow(
        project=project,
        username="reviewer",
        project_repository=repository,
        file_service=FileImportService(repository),
        orchestrator=AuditOrchestrator(
            repository,
            DocumentExtractionService(),
            RuleRegistry(),
            NoOpReviewLlm(),
        ),
        issue_service=IssueService(),
        advice_service=AdviceService(FakeAdvice()),
        conversation_service=ConversationService(FakeAdvice()),
        export_service=export_service,
        **kwargs,
    )
