from __future__ import annotations

from pathlib import Path

import pytest
from openpyxl import Workbook

from asset_based_agent.report_review_app.domain.enums import IssueStatus, RiskLevel
from asset_based_agent.report_review_app.domain.models import IssueLocation, ReviewIssue
from asset_based_agent.report_review_app.repositories.issue_repository import (
    IssueRepository,
)
from asset_based_agent.report_review_app.services.agent_gateway import (
    AdviceResult,
    ConversationTurnResult,
)
from asset_based_agent.report_review_app.services.conversation_service import (
    ConversationService,
    HiddenWorkbookContextError,
)


class RecordingProvider:
    def __init__(self) -> None:
        self.requests = []

    def continue_conversation(self, request):
        self.requests.append(request)
        return ConversationTurnResult(reply="请先核对金额，再修改结论。")


def issue(*, table: str = "汇总表", original_text: str = "B1=100") -> ReviewIssue:
    return ReviewIssue(
        issue_id="ISSUE-1",
        fingerprint="fingerprint",
        source_file_id="FILE-1",
        source_file_name="review.xlsx",
        category="data",
        risk_level=RiskLevel.HIGH,
        status=IssueStatus.NEW,
        location=IssueLocation(table=table, cell="B1"),
        original_text=original_text,
        description="金额需要核对",
        confidence=0.9,
        first_seen_round=1,
        last_seen_round=1,
    )


def paths(tmp_path: Path, review_issue: ReviewIssue):
    issues_path = tmp_path / "issues.json"
    advice_path = tmp_path / "advice.json"
    conversation_path = tmp_path / "conversations.json"
    repository = IssueRepository()
    repository.save_issues(
        issues_path,
        project_id="PROJECT-1",
        round_number=1,
        issues=[review_issue],
    )
    repository.save_advice(
        advice_path,
        {
            "schema_version": "1.0",
            "items": {
                review_issue.issue_id: {
                    "result": AdviceResult(
                        issue_id=review_issue.issue_id,
                        explanation="先核对原始资料",
                    ).model_dump(mode="json")
                }
            },
        },
    )
    return issues_path, advice_path, conversation_path


def test_conversation_service_persists_and_restores_multiple_turns(
    tmp_path: Path,
) -> None:
    provider = RecordingProvider()
    service = ConversationService(provider)
    issues_path, advice_path, conversation_path = paths(tmp_path, issue())

    first = service.continue_conversation(
        issues_path,
        advice_path,
        conversation_path,
        issue_id="ISSUE-1",
        project_id="PROJECT-1",
        user_message="第一步应该核对什么？",
        workbook_paths=[],
    )
    second = service.continue_conversation(
        issues_path,
        advice_path,
        conversation_path,
        issue_id="ISSUE-1",
        project_id="PROJECT-1",
        user_message="核对后应该怎么写？",
        workbook_paths=[],
    )

    assert [message.role for message in first] == ["user", "assistant"]
    assert [message.role for message in second] == [
        "user",
        "assistant",
        "user",
        "assistant",
    ]
    assert len(provider.requests[1].messages) == 2
    assert provider.requests[1].advice.explanation == "先核对原始资料"
    assert service.load_messages(
        conversation_path,
        issue_id="ISSUE-1",
    ) == second


def test_conversation_service_rejects_hidden_workbook_context_before_llm(
    tmp_path: Path,
) -> None:
    provider = RecordingProvider()
    service = ConversationService(provider)
    review_issue = issue(
        table="汇总表",
        original_text="B1=='隐藏测算'!B2",
    )
    issues_path, advice_path, conversation_path = paths(tmp_path, review_issue)
    workbook_path = tmp_path / "review.xlsx"
    workbook = Workbook()
    workbook.active.title = "汇总表"
    hidden = workbook.create_sheet("隐藏测算")
    hidden.sheet_state = "hidden"
    hidden["B2"] = 100
    workbook.save(workbook_path)

    with pytest.raises(HiddenWorkbookContextError):
        service.continue_conversation(
            issues_path,
            advice_path,
            conversation_path,
            issue_id="ISSUE-1",
            project_id="PROJECT-1",
            user_message="请分析这个公式。",
            workbook_paths=[workbook_path],
        )

    assert provider.requests == []
    assert not conversation_path.exists()


def test_conversation_service_clear_removes_only_selected_issue(
    tmp_path: Path,
) -> None:
    provider = RecordingProvider()
    service = ConversationService(provider)
    issues_path, advice_path, conversation_path = paths(tmp_path, issue())
    service.continue_conversation(
        issues_path,
        advice_path,
        conversation_path,
        issue_id="ISSUE-1",
        project_id="PROJECT-1",
        user_message="如何修改？",
        workbook_paths=[],
    )

    service.clear(conversation_path, issue_id="ISSUE-1")

    assert service.load_messages(
        conversation_path,
        issue_id="ISSUE-1",
    ) == []
