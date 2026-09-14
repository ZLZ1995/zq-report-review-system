from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from asset_based_agent.report_review_app.domain.enums import IssueStatus, RiskLevel
from asset_based_agent.report_review_app.domain.models import IssueLocation, ReviewIssue
from asset_based_agent.report_review_app.services.agent_gateway import (
    ConversationMessage,
)
from asset_based_agent.report_review_app.ui.issue_card import IssueCard


def issue(status: IssueStatus = IssueStatus.NEW) -> ReviewIssue:
    return ReviewIssue(
        issue_id="ISSUE-1",
        fingerprint="fingerprint",
        source_file_id="FILE-1",
        source_file_name="report.docx",
        category="data",
        risk_level=RiskLevel.HIGH,
        status=status,
        location=IssueLocation(chapter="结论", paragraph=1),
        original_text="100",
        description="value mismatch",
        confidence=0.9,
        first_seen_round=1,
        last_seen_round=1,
        ignored=status == IssueStatus.IGNORED,
    )


def application() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_issue_card_exposes_status_and_advice_actions() -> None:
    application()
    card = IssueCard(issue())

    assert card.status_label.text() == "本轮新发现"
    assert card.advice_button.text() == "寻求建议"
    assert card.ignore_button.text() == "忽略"
    card.set_advice(
        explanation="核对金额",
        checks=["检查测算表"],
        suggested_revision="建议例文",
    )
    assert card.advice_view.isHidden() is False
    assert "建议例文" in card.advice_view.toPlainText()
    assert card.conversation_button.text() == "进一步对话"
    assert card.conversation_button.isHidden() is False


def test_issue_card_emits_conversation_message_and_renders_history() -> None:
    application()
    card = IssueCard(issue())
    card.set_advice(
        explanation="核对金额",
        checks=[],
        suggested_revision="",
    )
    toggled = []
    sent = []
    card.conversation_toggled.connect(toggled.append)
    card.conversation_send_requested.connect(
        lambda issue_id, message: sent.append((issue_id, message))
    )

    card.conversation_button.click()
    card.set_conversation_open(True)
    card.conversation_input.setPlainText("应该先改哪里？")
    card.conversation_send_button.click()
    card.set_conversation_messages(
        [
            ConversationMessage(
                role="user",
                content="应该先改哪里？",
                created_at="2026-07-31T00:00:00+00:00",
            ),
            ConversationMessage(
                role="assistant",
                content="先核对原始金额。",
                created_at="2026-07-31T00:00:01+00:00",
            ),
        ]
    )

    assert toggled == ["ISSUE-1"]
    assert sent == [("ISSUE-1", "应该先改哪里？")]
    assert "用户：应该先改哪里？" in card.conversation_history.toPlainText()
    assert "审核助手：先核对原始金额。" in card.conversation_history.toPlainText()
    assert card.copy_final_button.isEnabled() is True


def test_ignored_issue_card_disables_actions() -> None:
    application()
    card = IssueCard(issue(IssueStatus.IGNORED))

    assert card.status_label.text() == "已忽略"
    assert card.advice_button.isEnabled() is False
    assert card.ignore_button.isEnabled() is False
