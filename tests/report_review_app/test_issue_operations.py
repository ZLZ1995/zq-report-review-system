from __future__ import annotations

from pathlib import Path

import pytest

from asset_based_agent.report_review_app.domain.enums import IssueStatus, RiskLevel
from asset_based_agent.report_review_app.domain.models import IssueLocation, ReviewIssue
from asset_based_agent.report_review_app.repositories.issue_repository import (
    IssueRepository,
)
from asset_based_agent.report_review_app.services.advice_service import AdviceService
from asset_based_agent.report_review_app.services.agent_gateway import AdviceResult
from asset_based_agent.report_review_app.services.issue_service import (
    IgnoredIssueIsImmutableError,
    IssueService,
)


def issue() -> ReviewIssue:
    return ReviewIssue(
        issue_id="ISSUE-1",
        fingerprint="fingerprint",
        source_file_id="FILE-1",
        source_file_name="report.docx",
        category="data",
        risk_level=RiskLevel.HIGH,
        status=IssueStatus.NEW,
        location=IssueLocation(paragraph=1),
        original_text="100",
        description="value mismatch",
        confidence=0.9,
        first_seen_round=1,
        last_seen_round=1,
    )


class FakeAdviceProvider:
    calls = 0

    def generate_advice(self, request):
        self.calls += 1
        return AdviceResult(
            issue_id=request.issue.issue_id,
            explanation="核对测算表与报告结论。",
            checks=["核对金额", "核对单位"],
            suggested_revision="建议例文",
        )


def prepare_issues(tmp_path: Path) -> Path:
    path = tmp_path / "issues.json"
    IssueRepository().save_issues(
        path,
        project_id="PROJECT-1",
        round_number=1,
        issues=[issue()],
    )
    return path


def test_ignore_is_persisted_and_cannot_be_reversed(tmp_path: Path) -> None:
    path = prepare_issues(tmp_path)
    service = IssueService()

    ignored = service.ignore(
        path,
        project_id="PROJECT-1",
        round_number=1,
        issue_id="ISSUE-1",
        username="reviewer",
    )

    assert ignored.status == IssueStatus.IGNORED
    assert ignored.ignored_by == "reviewer"
    with pytest.raises(IgnoredIssueIsImmutableError):
        service.ignore(
            path,
            project_id="PROJECT-1",
            round_number=1,
            issue_id="ISSUE-1",
            username="reviewer",
        )


def test_advice_is_persisted_and_cached(tmp_path: Path) -> None:
    issues_path = prepare_issues(tmp_path)
    advice_path = tmp_path / "advice.json"
    provider = FakeAdviceProvider()
    service = AdviceService(provider)

    first = service.request_advice(
        issues_path,
        advice_path,
        issue_id="ISSUE-1",
        project_id="PROJECT-1",
    )
    second = service.request_advice(
        issues_path,
        advice_path,
        issue_id="ISSUE-1",
        project_id="PROJECT-1",
    )

    assert first == second
    assert provider.calls == 1
    assert first.suggested_revision == "建议例文"


def test_ignored_issue_cannot_request_advice(tmp_path: Path) -> None:
    issues_path = prepare_issues(tmp_path)
    IssueService().ignore(
        issues_path,
        project_id="PROJECT-1",
        round_number=1,
        issue_id="ISSUE-1",
        username="reviewer",
    )

    with pytest.raises(IgnoredIssueIsImmutableError):
        AdviceService(FakeAdviceProvider()).request_advice(
            issues_path,
            tmp_path / "advice.json",
            issue_id="ISSUE-1",
            project_id="PROJECT-1",
        )
