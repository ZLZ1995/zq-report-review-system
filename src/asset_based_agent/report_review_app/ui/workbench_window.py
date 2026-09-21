"""Main local review workbench."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from time import monotonic

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ..branding import APPLICATION_NAME
from ..domain.enums import FileRole, IssueStatus, ProjectStatus, RoundStatus
from ..domain.models import AuditProject, ReviewIssue
from ..repositories.issue_repository import IssueRepository
from ..repositories.project_repository import ProjectRepository
from ..services.advice_service import AdviceService
from ..services.audit_orchestrator import AuditOrchestrator
from ..services.conversation_service import ConversationService
from ..services.file_service import (
    FileImportService,
    LegacyOfficeFormatError,
    UnsupportedFileTypeError,
)
from ..services.issue_service import IssueService
from ..services.recovery_service import RecoveryService
from ..services.report_export_service import ReportExportService
from ..workers.function_worker import FunctionWorker
from .issue_card import IssueCard
from .replacement_dialog import ReplacementDialog

ROLE_LABELS = {
    FileRole.MAIN_REPORT: "主报告",
    FileRole.VALUATION_EXPLANATION: "评估说明",
    FileRole.CALCULATION_WORKBOOK: "测算表",
    FileRole.REFERENCE_DOCUMENT: "参考材料",
    FileRole.UNKNOWN: "待确认",
}


class WorkbenchWindow(QMainWindow):
    back_requested = Signal()

    def __init__(
        self,
        *,
        project: AuditProject,
        username: str,
        project_repository: ProjectRepository,
        file_service: FileImportService,
        orchestrator: AuditOrchestrator,
        issue_service: IssueService,
        advice_service: AdviceService,
        conversation_service: ConversationService,
        export_service: ReportExportService,
        model_options: list[tuple[str, str]] | None = None,
        model_selected_callback: Callable[[str], None] | None = None,
        balance_display: str | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.project = project
        self.username = username
        self.project_repository = project_repository
        self.file_service = file_service
        self.orchestrator = orchestrator
        self.issue_service = issue_service
        self.advice_service = advice_service
        self.conversation_service = conversation_service
        self.export_service = export_service
        self.model_options = model_options or []
        self.model_selected_callback = model_selected_callback
        self.balance_display = balance_display
        self.issue_repository = IssueRepository()
        self.worker: FunctionWorker | None = None
        self.background_workers: list[FunctionWorker] = []
        self.cards: dict[str, IssueCard] = {}
        self._audit_started_at: float | None = None
        self.setWindowTitle(f"{APPLICATION_NAME} - {project.name}")
        self.setMinimumSize(1180, 760)
        self._build_ui()
        self._refresh_all()

    def _build_ui(self) -> None:
        container = QWidget()
        root = QVBoxLayout(container)

        header = QHBoxLayout()
        back = QPushButton("返回项目列表")
        back.clicked.connect(self.back_requested.emit)
        header.addWidget(back)
        header.addWidget(QLabel(f"项目：{self.project.name}"))
        header.addStretch(1)
        header.addWidget(QLabel(f"用户：{self.username}"))
        root.addLayout(header)

        file_buttons = QHBoxLayout()
        self.files_toggle_button = QToolButton()
        self.files_toggle_button.setCheckable(True)
        self.files_toggle_button.setChecked(True)
        self.files_toggle_button.setArrowType(Qt.ArrowType.UpArrow)
        self.files_toggle_button.setToolButtonStyle(
            Qt.ToolButtonStyle.ToolButtonTextBesideIcon
        )
        self.files_toggle_button.setText("文件列表（0）")
        self.files_toggle_button.setToolTip("收起或展开上传文件列表")
        self.files_toggle_button.clicked.connect(self._set_files_expanded)
        file_buttons.addWidget(self.files_toggle_button)
        upload = QPushButton("上传文件")
        upload.clicked.connect(self._upload_initial_files)
        file_buttons.addWidget(upload)
        file_buttons.addStretch(1)
        root.addLayout(file_buttons)

        self.file_table = QTableWidget(0, 3)
        self.file_table.setHorizontalHeaderLabels(["文件名", "文件角色", "所属轮次"])
        self.file_table.horizontalHeader().setStretchLastSection(True)
        self.file_table.setMaximumHeight(280)
        root.addWidget(self.file_table)

        audit_row = QHBoxLayout()
        self.audit_button = QPushButton("审核报告")
        self.audit_button.clicked.connect(self._start_current_round)
        self.model_combo: QComboBox | None = None
        if self.model_options:
            audit_row.addWidget(QLabel("审核模型"))
            self.model_combo = QComboBox()
            for model_id, display_name in self.model_options:
                self.model_combo.addItem(display_name, model_id)
            self.model_combo.currentIndexChanged.connect(self._model_changed)
            audit_row.addWidget(self.model_combo)
        if self.balance_display is not None:
            audit_row.addWidget(QLabel(f"余额：{self.balance_display} 元"))
        self.status_label = QLabel("等待上传文件")
        audit_row.addWidget(self.audit_button)
        audit_row.addWidget(self.status_label)
        audit_row.addStretch(1)
        root.addLayout(audit_row)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        root.addWidget(self.progress_bar)
        self.progress_detail_label = QLabel("尚未开始审核")
        self.progress_detail_label.setStyleSheet("color: #475467;")
        root.addWidget(self.progress_detail_label)

        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.cards_container = QWidget()
        self.cards_layout = QVBoxLayout(self.cards_container)
        self.cards_layout.addStretch(1)
        self.scroll_area.setWidget(self.cards_container)
        root.addWidget(self.scroll_area, 1)

        actions = QHBoxLayout()
        self.replace_button = QPushButton("上传修改文件")
        self.finish_button = QPushButton("完成并生成审核报告")
        self.resume_button = QPushButton("继续未完成审核")
        self.replace_button.clicked.connect(self._open_replacement_dialog)
        self.finish_button.clicked.connect(self._finish_project)
        self.resume_button.clicked.connect(self._resume_audit)
        actions.addWidget(self.resume_button)
        actions.addWidget(self.replace_button)
        actions.addWidget(self.finish_button)
        actions.addStretch(1)
        root.addLayout(actions)
        self.setCentralWidget(container)

    def _model_changed(self, index: int) -> None:
        if self.model_combo is None or self.model_selected_callback is None:
            return
        model_id = self.model_combo.itemData(index)
        if isinstance(model_id, str):
            self.model_selected_callback(model_id)

        self.progress_timer = QTimer(self)
        self.progress_timer.setInterval(500)
        self.progress_timer.timeout.connect(self._poll_progress)

    def _refresh_all(self) -> None:
        self.project = self.project_repository.get(self.project.project_id)
        self._refresh_files()
        self._load_latest_issues()
        has_files = bool(
            [
                item
                for item in self.project.files
                if item.round_number == max(self.project.current_round, 1)
            ]
        )
        running = self.worker is not None and self.worker.isRunning()
        self.audit_button.setEnabled(has_files and not running)
        completed = any(
            item.status == RoundStatus.COMPLETED for item in self.project.rounds
        )
        self.replace_button.setVisible(completed)
        self.finish_button.setVisible(completed)
        recovery_states = RecoveryService().inspect(self.project)
        self.resume_button.setVisible(
            any(item.recoverable for item in recovery_states)
        )
        if completed and not running:
            self.status_label.setText(
                f"{_round_label(self._latest_completed_round())}审核已完成"
            )

    def _refresh_files(self) -> None:
        self.file_table.setRowCount(0)
        for source in sorted(
            self.project.files,
            key=lambda item: (item.round_number, item.original_name),
        ):
            row = self.file_table.rowCount()
            self.file_table.insertRow(row)
            self.file_table.setItem(row, 0, QTableWidgetItem(source.original_name))
            combo = QComboBox()
            for role, label in ROLE_LABELS.items():
                combo.addItem(label, role)
            combo.setCurrentIndex(combo.findData(source.role))
            combo.currentIndexChanged.connect(
                lambda _index, file_id=source.file_id, widget=combo: self._change_role(
                    file_id,
                    widget.currentData(),
                )
            )
            self.file_table.setCellWidget(row, 1, combo)
            self.file_table.setItem(row, 2, QTableWidgetItem(str(source.round_number)))
        self.files_toggle_button.setText(
            f"文件列表（{self.file_table.rowCount()}）"
        )

    def _set_files_expanded(self, expanded: bool) -> None:
        self.file_table.setVisible(expanded)
        self.files_toggle_button.setArrowType(
            Qt.ArrowType.UpArrow if expanded else Qt.ArrowType.DownArrow
        )
        self.files_toggle_button.setToolTip(
            "收起上传文件列表" if expanded else "展开上传文件列表"
        )

    def _upload_initial_files(self) -> None:
        filenames, _ = QFileDialog.getOpenFileNames(
            self,
            "选择审核文件",
            "",
            "审核文件 (*.docx *.xlsx *.xlsm *.pdf *.doc *.xls)",
        )
        if not filenames:
            return
        round_number = max(self.project.current_round, 1)
        if any(item.status == RoundStatus.COMPLETED for item in self.project.rounds):
            QMessageBox.information(
                self,
                "请使用修改文件入口",
                "已有完成轮次，请点击“上传修改文件”开启下一轮。",
            )
            return
        try:
            self.file_service.import_files(
                self.project,
                [Path(filename) for filename in filenames],
                round_number=round_number,
            )
        except (LegacyOfficeFormatError, UnsupportedFileTypeError, OSError) as exc:
            QMessageBox.warning(self, "文件导入失败", str(exc))
        self._refresh_all()

    def _change_role(self, file_id: str, role: FileRole) -> None:
        for source in self.project.files:
            if source.file_id == file_id:
                source.role = role
                self.project_repository.save(self.project)
                return

    def _start_current_round(self) -> None:
        self._start_audit(max(self.project.current_round, 1))

    def _start_audit(self, round_number: int) -> None:
        if self.worker is not None and self.worker.isRunning():
            return
        self.status_label.setText(f"{_round_label(round_number)}审核进行中")
        self.audit_button.setEnabled(False)
        self.replace_button.setEnabled(False)
        self.finish_button.setEnabled(False)
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat("0%")
        self.progress_detail_label.setText("正在准备审核任务 · 已用时 00:00")
        self._audit_started_at = monotonic()
        self.worker = FunctionWorker(
            lambda: self.orchestrator.run_round(self.project, round_number),
            self,
        )
        self.worker.succeeded.connect(self._audit_succeeded)
        self.worker.failed.connect(self._audit_failed)
        self.worker.finished.connect(self._worker_finished)
        self.progress_timer.start()
        self.worker.start()

    def _audit_succeeded(self, result) -> None:
        self.status_label.setText(f"{_round_label(result.round_number)}审核已完成")
        self.progress_bar.setValue(100)
        self.progress_bar.setFormat("100%")
        elapsed = _elapsed_seconds(self._audit_started_at)
        self.progress_detail_label.setText(
            _format_progress_detail(
                {"detail": "审核已完成"},
                elapsed_seconds=elapsed,
            )
        )
        self._refresh_all()

    def _audit_failed(self, message: str) -> None:
        self._poll_progress()
        self.status_label.setText("审核暂停或失败")
        QMessageBox.warning(self, "审核未完成", _format_audit_error(message))
        self._refresh_all()

    def _worker_finished(self) -> None:
        self.progress_timer.stop()
        self.replace_button.setEnabled(True)
        self.finish_button.setEnabled(True)
        self.audit_button.setEnabled(True)
        if self.worker is not None:
            self.worker.deleteLater()
        self.worker = None
        self._audit_started_at = None

    def _poll_progress(self) -> None:
        round_number = max(self.project.current_round, 1)
        path = (
            Path(self.project.project_path)
            / "rounds"
            / f"round-{round_number:03d}"
            / "progress.json"
        )
        if not path.is_file():
            return
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        percent = max(0, min(100, int(payload.get("percent") or 0)))
        self.progress_bar.setValue(percent)
        self.progress_bar.setFormat(f"{percent}%")
        self.progress_detail_label.setText(
            _format_progress_detail(
                payload,
                elapsed_seconds=_elapsed_seconds(self._audit_started_at),
            )
        )

    def _load_latest_issues(self) -> None:
        self._clear_cards()
        latest = self._latest_completed_record()
        if latest is None or not Path(latest.issues_path).is_file():
            self.cards_layout.insertWidget(0, QLabel("审核完成后将在此显示问题卡片。"))
            return
        issues = self.issue_repository.load_issues(Path(latest.issues_path))
        advice_items = (
            self.issue_repository.load_advice(
                Path(latest.issues_path).with_name("advice.json")
            ).get("items")
            or {}
        )
        conversation_path = Path(latest.issues_path).with_name(
            "conversations.json"
        )
        grouped: dict[str, list[ReviewIssue]] = {}
        for issue in issues:
            grouped.setdefault(issue.source_file_name, []).append(issue)
        insert_index = 0
        for file_name, file_issues in grouped.items():
            heading = QLabel(file_name)
            heading.setStyleSheet("font-size: 16px; font-weight: 600; color: #243447;")
            self.cards_layout.insertWidget(insert_index, heading)
            insert_index += 1
            for issue in file_issues:
                card = IssueCard(issue)
                card.advice_requested.connect(self._request_advice)
                card.ignore_requested.connect(self._ignore_issue)
                card.conversation_toggled.connect(self._toggle_conversation)
                card.conversation_send_requested.connect(
                    self._send_conversation
                )
                card.conversation_clear_requested.connect(
                    self._clear_conversation
                )
                advice_item = advice_items.get(issue.issue_id)
                if advice_item and advice_item.get("result"):
                    result = advice_item["result"]
                    card.set_advice(
                        explanation=result.get("explanation", ""),
                        checks=result.get("checks") or [],
                        suggested_revision=result.get(
                            "suggested_revision", ""
                        ),
                    )
                card.set_conversation_messages(
                    self.conversation_service.load_messages(
                        conversation_path,
                        issue_id=issue.issue_id,
                    )
                )
                self.cards[issue.issue_id] = card
                self.cards_layout.insertWidget(insert_index, card)
                insert_index += 1

    def _clear_cards(self) -> None:
        self.cards.clear()
        while self.cards_layout.count() > 1:
            item = self.cards_layout.takeAt(0)
            if item is None:
                continue
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _request_advice(self, issue_id: str) -> None:
        latest = self._latest_completed_record()
        if latest is None:
            return
        advice_path = Path(latest.issues_path).with_name("advice.json")
        card = self.cards[issue_id]
        card.advice_button.setEnabled(False)
        worker = FunctionWorker(
            lambda: self.advice_service.request_advice(
                Path(latest.issues_path),
                advice_path,
                issue_id=issue_id,
                project_id=self.project.project_id,
            ),
            self,
        )
        worker.succeeded.connect(
            lambda result: card.set_advice(
                explanation=result.explanation,
                checks=result.checks,
                suggested_revision=result.suggested_revision,
            )
        )
        worker.failed.connect(
            lambda message: QMessageBox.warning(self, "建议生成失败", message)
        )
        worker.finished.connect(lambda: card.advice_button.setEnabled(True))
        worker.finished.connect(lambda: self._release_background_worker(worker))
        self.background_workers.append(worker)
        worker.start()

    def _toggle_conversation(self, issue_id: str) -> None:
        target = self.cards.get(issue_id)
        if target is None or not target.conversation_button.isEnabled():
            return
        should_open = target.conversation_panel.isHidden()
        for card in self.cards.values():
            card.set_conversation_open(False)
        if should_open:
            target.set_conversation_open(True)

    def _send_conversation(self, issue_id: str, message: str) -> None:
        latest = self._latest_completed_record()
        card = self.cards.get(issue_id)
        if latest is None or card is None:
            return
        issues_path = Path(latest.issues_path)
        advice_path = issues_path.with_name("advice.json")
        conversation_path = issues_path.with_name("conversations.json")
        workbook_paths = [
            Path(item.original_path)
            for item in self.project.files
            if item.role == FileRole.CALCULATION_WORKBOOK
            and item.round_number == latest.round_number
            and Path(item.original_path).is_file()
        ]
        card.set_conversation_busy(True)
        worker = FunctionWorker(
            lambda: self.conversation_service.continue_conversation(
                issues_path,
                advice_path,
                conversation_path,
                issue_id=issue_id,
                project_id=self.project.project_id,
                user_message=message,
                workbook_paths=workbook_paths,
            ),
            self,
        )
        worker.succeeded.connect(card.set_conversation_messages)
        worker.failed.connect(
            lambda error: QMessageBox.warning(
                self, "进一步对话失败", error
            )
        )
        worker.finished.connect(
            lambda: card.set_conversation_busy(False)
        )
        worker.finished.connect(lambda: self._release_background_worker(worker))
        self.background_workers.append(worker)
        worker.start()

    def _clear_conversation(self, issue_id: str) -> None:
        card = self.cards.get(issue_id)
        latest = self._latest_completed_record()
        if card is None or latest is None:
            return
        answer = QMessageBox.question(
            self,
            "清空对话",
            "确定清空当前问题的本地对话记录吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.conversation_service.clear(
            Path(latest.issues_path).with_name("conversations.json"),
            issue_id=issue_id,
        )
        card.set_conversation_messages([])

    def _ignore_issue(self, issue_id: str) -> None:
        answer = QMessageBox.warning(
            self,
            "确认忽略",
            "忽略后不可恢复，且后续轮次不再提示该问题。是否继续？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        latest = self._latest_completed_record()
        if latest is None:
            return
        self.issue_service.ignore(
            Path(latest.issues_path),
            project_id=self.project.project_id,
            round_number=latest.round_number,
            issue_id=issue_id,
            username=self.username,
        )
        self._load_latest_issues()

    def _open_replacement_dialog(self) -> None:
        latest_round = self._latest_completed_round()
        current_files = [
            item for item in self.project.files if item.round_number == latest_round
        ]
        dialog = ReplacementDialog(current_files, self)
        if not dialog.exec():
            return
        next_round = latest_round + 1
        selections = dialog.selections()
        paths = [path for path, _target in selections]
        replacement_overrides = {
            str(path.resolve()): target
            for path, target in selections
            if target
        }
        try:
            self.file_service.import_files(
                self.project,
                paths,
                round_number=next_round,
                replacement_overrides=replacement_overrides,
            )
        except (LegacyOfficeFormatError, UnsupportedFileTypeError, OSError) as exc:
            QMessageBox.warning(self, "文件导入失败", str(exc))
            return
        self._refresh_all()
        self._start_audit(next_round)

    def _resume_audit(self) -> None:
        states = [
            item for item in RecoveryService().inspect(self.project) if item.recoverable
        ]
        if not states:
            self._refresh_all()
            return
        state = max(states, key=lambda item: item.round_number)
        self._start_audit(state.round_number)

    def _finish_project(self) -> None:
        latest = self._latest_completed_record()
        if latest is None:
            return
        issues = self.issue_repository.load_issues(Path(latest.issues_path))
        unresolved = [
            issue
            for issue in issues
            if issue.status
            in {
                IssueStatus.NEW,
                IssueStatus.UNMODIFIED,
                IssueStatus.INCORRECT_FIX,
                IssueStatus.UNCERTAIN,
            }
        ]
        if unresolved:
            answer = QMessageBox.warning(
                self,
                "仍有未解决问题",
                f"仍有{len(unresolved)}项问题未解决。是否继续生成最终审核报告？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        selected_path, _selected_filter = QFileDialog.getSaveFileName(
            self,
            "选择审核报告保存位置",
            "审核意见.docx",
            "Word 文档 (*.docx)",
        )
        if not selected_path:
            return
        destination = Path(selected_path)
        if destination.suffix.lower() != ".docx":
            destination = destination.with_suffix(".docx")
        try:
            _summary_path, report_path = self.export_service.export(
                self.project,
                destination,
            )
            self.project.status = ProjectStatus.COMPLETED
            self.project.final_report_path = str(report_path)
            self.project_repository.save(self.project)
        except Exception as exc:
            QMessageBox.warning(self, "报告生成失败", str(exc))
            return
        QMessageBox.information(self, "审核报告已生成", str(report_path))
        self._refresh_all()

    def _latest_completed_record(self):
        completed = [
            item for item in self.project.rounds if item.status == RoundStatus.COMPLETED
        ]
        if not completed:
            return None
        return max(completed, key=lambda item: item.round_number)

    def _latest_completed_round(self) -> int:
        record = self._latest_completed_record()
        return record.round_number if record else 0

    def _release_background_worker(self, worker: FunctionWorker) -> None:
        if worker in self.background_workers:
            self.background_workers.remove(worker)
        worker.deleteLater()


def _round_label(round_number: int) -> str:
    if round_number == 1:
        return "第一轮"
    if round_number == 2:
        return "第二轮"
    return f"第{round_number}轮"


def _format_audit_error(message: str) -> str:
    if message.startswith("ReviewResponseSchemaError:"):
        return (
            "审核结果格式不符合程序要求。\n\n"
            "模型已经成功返回结果，但部分审核字段格式无法识别。"
            "本轮上传文件未被修改，您可以更新程序或调整模型配置后重新审核。\n\n"
            "错误编号：LLM_RESPONSE_SCHEMA_ERROR"
        )
    if message.startswith("ReviewNetworkError:"):
        if "IncompleteRead" in message or "RemoteDisconnected" in message:
            reason = "模型服务的响应在传输过程中中断。"
        else:
            reason = "程序暂时无法连接模型服务。"
        return (
            f"{reason}\n\n"
            "程序已经自动重试，但仍未成功。本轮上传文件未被修改，"
            "当前审核进度已经保留。\n\n"
            "请检查本机网络、API地址及中转站状态，然后点击"
            "“继续未完成审核”。\n\n"
            "错误编号：LLM_NETWORK_INTERRUPTED"
        )
    return message


def _format_progress_detail(
    payload: dict[str, object],
    *,
    elapsed_seconds: int,
) -> str:
    parts = [str(payload.get("detail") or "正在处理审核任务")]
    batch_index = payload.get("batch_index")
    batch_total = payload.get("batch_total")
    if batch_index and batch_total:
        parts.append(f"第 {batch_index}/{batch_total} 批")
    attempt = payload.get("attempt")
    attempt_total = payload.get("attempt_total")
    if attempt and attempt_total and int(attempt_total) > 1:
        parts.append(f"第 {attempt}/{attempt_total} 次尝试")
    minutes, seconds = divmod(max(0, elapsed_seconds), 60)
    parts.append(f"已用时 {minutes:02d}:{seconds:02d}")
    return " · ".join(parts)


def _elapsed_seconds(started_at: float | None) -> int:
    if started_at is None:
        return 0
    return max(0, int(monotonic() - started_at))
