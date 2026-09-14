"""User-driven issue state operations."""

from __future__ import annotations

from pathlib import Path

from ..domain.enums import IssueStatus
from ..domain.models import IssueHistoryEntry, ReviewIssue, utc_now
from ..repositories.issue_repository import IssueRepository


class IssueNotFoundError(LookupError):
    pass


class IgnoredIssueIsImmutableError(ValueError):
    pass


class IssueService:
    def __init__(self, repository: IssueRepository | None = None) -> None:
        self.repository = repository or IssueRepository()

    def ignore(
        self,
        issues_path: Path,
        *,
        project_id: str,
        round_number: int,
        issue_id: str,
        username: str,
    ) -> ReviewIssue:
        issues = self.repository.load_issues(issues_path)
        issue = _find_issue(issues, issue_id)
        if issue.ignored:
            raise IgnoredIssueIsImmutableError("ignored issue cannot be changed")
        issue.status = IssueStatus.IGNORED
        issue.ignored = True
        issue.ignored_at = utc_now()
        issue.ignored_by = username
        issue.history.append(
            IssueHistoryEntry(
                round_number=round_number,
                status=IssueStatus.IGNORED,
                note=f"ignored by {username}",
            )
        )
        self.repository.save_issues(
            issues_path,
            project_id=project_id,
            round_number=round_number,
            issues=issues,
        )
        return issue


def _find_issue(issues: list[ReviewIssue], issue_id: str) -> ReviewIssue:
    for issue in issues:
        if issue.issue_id == issue_id:
            return issue
    raise IssueNotFoundError(f"issue not found: {issue_id}")
