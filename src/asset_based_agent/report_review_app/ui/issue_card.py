"""Card widget for one structured review issue."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
)

from ..domain.enums import IssueStatus
from ..domain.models import ReviewIssue
from ..services.agent_gateway import ConversationMessage
from .styles import STATUS_COLORS, STATUS_LABELS


class IssueCard(QFrame):
    advice_requested = Signal(str)
    ignore_requested = Signal(str)
    conversation_toggled = Signal(str)
    conversation_send_requested = Signal(str, str)
    conversation_clear_requested = Signal(str)

    def __init__(self, issue: ReviewIssue, parent=None) -> None:
        super().__init__(parent)
        self.issue = issue
        self.setObjectName("issueCard")
        self._build_ui()
        self._apply_status()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        header = QHBoxLayout()
        self.file_label = QLabel(self.issue.source_file_name)
        self.status_label = QLabel()
        header.addWidget(self.file_label)
        header.addStretch(1)
        header.addWidget(self.status_label)
        layout.addLayout(header)

        location = self._location_text()
        self.location_label = QLabel(location)
        self.location_label.setWordWrap(True)
        layout.addWidget(self.location_label)

        source_text = self.issue.origin or "legacy"
        evidence_text = self.issue.evidence_state or "unknown"
        self.provenance_label = QLabel(
            f"问题来源：{source_text}；证据状态：{evidence_text}"
        )
        self.provenance_label.setWordWrap(True)
        layout.addWidget(self.provenance_label)

        self.original_label = QLabel(self.issue.original_text or "无可展示原文")
        self.original_label.setWordWrap(True)
        layout.addWidget(self.original_label)

        self.description_label = QLabel(self.issue.description)
        self.description_label.setWordWrap(True)
        layout.addWidget(self.description_label)

        buttons = QHBoxLayout()
        self.advice_button = QPushButton("寻求建议")
        self.ignore_button = QPushButton("忽略")
        self.advice_button.clicked.connect(
            lambda: self.advice_requested.emit(self.issue.issue_id)
        )
        self.ignore_button.clicked.connect(
            lambda: self.ignore_requested.emit(self.issue.issue_id)
        )
        buttons.addWidget(self.advice_button)
        buttons.addWidget(self.ignore_button)
        buttons.addStretch(1)
        layout.addLayout(buttons)

        self.advice_view = QTextBrowser()
        self.advice_view.setVisible(False)
        layout.addWidget(self.advice_view)

        self.conversation_button = QPushButton("进一步对话")
        self.conversation_button.setVisible(False)
        self.conversation_button.clicked.connect(
            lambda: self.conversation_toggled.emit(self.issue.issue_id)
        )
        layout.addWidget(self.conversation_button)

        self.conversation_panel = QFrame()
        self.conversation_panel.setObjectName("conversationPanel")
        conversation_layout = QVBoxLayout(self.conversation_panel)
        conversation_layout.setContentsMargins(8, 8, 8, 8)
        conversation_layout.addWidget(QLabel("围绕当前问题继续讨论"))
        self.conversation_history = QTextBrowser()
        self.conversation_history.setMinimumHeight(120)
        self.conversation_history.setPlaceholderText("尚无进一步对话记录。")
        conversation_layout.addWidget(self.conversation_history)
        self.conversation_input = QPlainTextEdit()
        self.conversation_input.setPlaceholderText(
            "输入需要继续核对或推导的问题……"
        )
        self.conversation_input.setMaximumHeight(90)
        conversation_layout.addWidget(self.conversation_input)

        conversation_buttons = QHBoxLayout()
        self.conversation_send_button = QPushButton("发送")
        self.copy_final_button = QPushButton("复制最终方案")
        self.clear_conversation_button = QPushButton("清空对话")
        self.collapse_conversation_button = QPushButton("收起")
        self.copy_final_button.setEnabled(False)
        self.conversation_send_button.clicked.connect(self._send_conversation)
        self.copy_final_button.clicked.connect(self._copy_final_reply)
        self.clear_conversation_button.clicked.connect(
            lambda: self.conversation_clear_requested.emit(self.issue.issue_id)
        )
        self.collapse_conversation_button.clicked.connect(
            lambda: self.conversation_toggled.emit(self.issue.issue_id)
        )
        conversation_buttons.addWidget(self.conversation_send_button)
        conversation_buttons.addWidget(self.copy_final_button)
        conversation_buttons.addWidget(self.clear_conversation_button)
        conversation_buttons.addWidget(self.collapse_conversation_button)
        conversation_buttons.addStretch(1)
        conversation_layout.addLayout(conversation_buttons)
        self.conversation_panel.setVisible(False)
        layout.addWidget(self.conversation_panel)
        self._conversation_messages: list[ConversationMessage] = []

    def update_issue(self, issue: ReviewIssue) -> None:
        if issue.issue_id != self.issue.issue_id:
            raise ValueError("cannot replace card with a different issue")
        self.issue = issue
        self.status_label.setText(STATUS_LABELS[issue.status])
        self._apply_status()

    def set_advice(
        self,
        *,
        explanation: str,
        checks: list[str],
        suggested_revision: str,
    ) -> None:
        lines = [explanation]
        if checks:
            lines.append("\n需要核对：")
            lines.extend(f"• {item}" for item in checks)
        if suggested_revision:
            lines.append("\n建议例文：")
            lines.append(suggested_revision)
        self.advice_view.setPlainText("\n".join(lines))
        self.advice_view.setVisible(True)
        self.conversation_button.setVisible(True)

    def set_conversation_open(self, opened: bool) -> None:
        self.conversation_panel.setVisible(opened)
        self.conversation_button.setText(
            "收起对话" if opened else "进一步对话"
        )
        if opened:
            self.conversation_input.setFocus()

    def set_conversation_messages(
        self,
        messages: list[ConversationMessage],
    ) -> None:
        self._conversation_messages = list(messages)
        rendered = []
        for message in messages:
            speaker = "用户" if message.role == "user" else "审核助手"
            rendered.append(f"{speaker}：{message.content}")
        self.conversation_history.setPlainText("\n\n".join(rendered))
        self.copy_final_button.setEnabled(
            any(message.role == "assistant" for message in messages)
        )
        self.conversation_input.clear()
        scrollbar = self.conversation_history.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def set_conversation_busy(self, busy: bool) -> None:
        self.conversation_send_button.setEnabled(not busy)
        self.conversation_input.setEnabled(not busy)
        self.conversation_send_button.setText("正在分析…" if busy else "发送")

    def _apply_status(self) -> None:
        status = self.issue.status
        color = STATUS_COLORS[status]
        self.status_label.setText(STATUS_LABELS[status])
        self.setStyleSheet(
            "#issueCard {"
            f"background-color: {color};"
            "border: 1px solid rgba(40, 50, 65, 90);"
            "border-radius: 8px;"
            "padding: 8px;"
            "}"
        )
        ignored = status == IssueStatus.IGNORED
        self.advice_button.setEnabled(not ignored)
        self.ignore_button.setEnabled(not ignored)
        self.conversation_button.setEnabled(not ignored)
        self.conversation_input.setEnabled(not ignored)
        self.conversation_send_button.setEnabled(not ignored)

    def _location_text(self) -> str:
        locations = self.issue.occurrences or [self.issue.location]
        rendered = [self._one_location_text(location) for location in locations]
        return "；".join(
            f"位置{index}：{text}" for index, text in enumerate(rendered, start=1)
        )

    @staticmethod
    def _one_location_text(location) -> str:
        values = []
        if location.chapter:
            values.append(f"章节：{location.chapter}")
        if location.page:
            values.append(f"页码：{location.page}")
        if location.paragraph:
            values.append(f"段落：{location.paragraph}")
        if location.table:
            values.append(f"表格/工作表：{location.table}")
        if location.cell:
            values.append(f"位置：{location.cell}")
        return "，".join(values) or "待人工确认"

    def _send_conversation(self) -> None:
        message = self.conversation_input.toPlainText().strip()
        if message:
            self.conversation_send_requested.emit(self.issue.issue_id, message)

    def _copy_final_reply(self) -> None:
        for message in reversed(self._conversation_messages):
            if message.role == "assistant":
                QGuiApplication.clipboard().setText(message.content)
                return
