from __future__ import annotations

from copy import deepcopy

from asset_based_agent.report_review_app.domain.enums import IssueStatus, RiskLevel
from asset_based_agent.report_review_app.domain.models import IssueLocation, ReviewIssue
from asset_based_agent.report_review_app.services.issue_matcher import IssueMatcher


def make_issue(
    issue_id: str,
    source_file_id: str,
    text: str,
    *,
    status: IssueStatus = IssueStatus.NEW,
    ignored: bool = False,
) -> ReviewIssue:
    return ReviewIssue(
        issue_id=issue_id,
        fingerprint=f"fingerprint-{issue_id}",
        source_file_id=source_file_id,
        source_file_name=f"{source_file_id}.docx",
        category="data_inconsistency",
        risk_level=RiskLevel.HIGH,
        status=status,
        location=IssueLocation(paragraph=1),
        original_text=text,
        description="报告金额与测算表不一致",
        confidence=0.9,
        first_seen_round=1,
        last_seen_round=1,
        ignored=ignored,
    )


def test_unchanged_issue_keeps_id_and_becomes_unmodified() -> None:
    previous = make_issue("ISSUE-1", "OLD-FILE", "100")
    current = make_issue("TEMP", "NEW-FILE", "100")

    results = IssueMatcher().reconcile(
        [previous],
        [current],
        round_number=2,
        source_replacements={"OLD-FILE": "NEW-FILE"},
    )

    assert len(results) == 1
    assert results[0].issue_id == "ISSUE-1"
    assert results[0].status == IssueStatus.UNMODIFIED
    assert results[0].last_seen_round == 2


def test_changed_but_still_wrong_becomes_incorrect_fix() -> None:
    previous = make_issue("ISSUE-1", "OLD-FILE", "100")
    current = make_issue("TEMP", "NEW-FILE", "101")

    results = IssueMatcher().reconcile(
        [previous],
        [current],
        round_number=2,
        source_replacements={"OLD-FILE": "NEW-FILE"},
    )

    assert results[0].status == IssueStatus.INCORRECT_FIX


def test_missing_previous_issue_becomes_fixed_and_new_issue_is_added() -> None:
    previous = make_issue("ISSUE-1", "OLD-FILE", "100")
    new_issue = make_issue("ISSUE-2", "NEW-FILE", "different")
    new_issue.category = "template_residue"

    results = IssueMatcher().reconcile(
        [previous],
        [new_issue],
        round_number=2,
        source_replacements={"OLD-FILE": "NEW-FILE"},
    )

    by_id = {item.issue_id: item for item in results}
    assert by_id["ISSUE-1"].status == IssueStatus.FIXED
    assert by_id["ISSUE-2"].status == IssueStatus.NEW


def test_ignored_issue_does_not_reappear_as_new() -> None:
    previous = make_issue(
        "ISSUE-1",
        "OLD-FILE",
        "100",
        status=IssueStatus.IGNORED,
        ignored=True,
    )
    previous.ignored_by = "reviewer"
    current = deepcopy(previous)
    current.issue_id = "TEMP"
    current.source_file_id = "NEW-FILE"
    current.status = IssueStatus.NEW
    current.ignored = False
    current.ignored_by = None

    results = IssueMatcher().reconcile(
        [previous],
        [current],
        round_number=2,
        source_replacements={"OLD-FILE": "NEW-FILE"},
    )

    assert len(results) == 1
    assert results[0].issue_id == "ISSUE-1"
    assert results[0].status == IssueStatus.IGNORED
