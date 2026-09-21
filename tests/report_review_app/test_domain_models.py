from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from asset_based_agent.report_review_app.domain.enums import IssueStatus, RiskLevel
from asset_based_agent.report_review_app.domain.models import IssueLocation, ReviewIssue


def build_issue(**overrides) -> ReviewIssue:
    values = {
        "issue_id": "ISSUE-000001",
        "fingerprint": "abc123",
        "source_file_id": "FILE-000001",
        "source_file_name": "report.docx",
        "category": "data_inconsistency",
        "risk_level": RiskLevel.HIGH,
        "status": IssueStatus.NEW,
        "location": IssueLocation(chapter="result", page=1),
        "description": "Value mismatch",
        "confidence": 0.92,
        "first_seen_round": 1,
        "last_seen_round": 1,
    }
    values.update(overrides)
    return ReviewIssue(**values)


def test_issue_round_trips_through_json() -> None:
    issue = build_issue()

    restored = ReviewIssue.model_validate_json(issue.model_dump_json())

    assert restored == issue
    assert json.loads(issue.model_dump_json())["status"] == "new"


def test_ignored_issue_requires_consistent_status() -> None:
    with pytest.raises(ValidationError):
        build_issue(status=IssueStatus.IGNORED, ignored=False)


def test_last_seen_round_cannot_precede_first_seen_round() -> None:
    with pytest.raises(ValidationError):
        build_issue(first_seen_round=2, last_seen_round=1)


def test_unknown_persisted_fields_are_ignored_for_forward_compatibility() -> None:
    payload = build_issue().model_dump(mode="json")
    payload["future_field"] = {"enabled": True}

    restored = ReviewIssue.model_validate(payload)

    assert restored.issue_id == "ISSUE-000001"
