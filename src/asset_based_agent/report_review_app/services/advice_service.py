"""Per-card advice generation and persistence."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from ..domain.enums import IssueStatus
from ..domain.models import utc_now
from ..repositories.issue_repository import IssueRepository
from .agent_gateway import AdviceRequest, AdviceResult
from .issue_service import IgnoredIssueIsImmutableError, _find_issue


class AdviceProvider(Protocol):
    def generate_advice(self, request: AdviceRequest) -> AdviceResult:
        ...


class AdviceService:
    def __init__(
        self,
        provider: AdviceProvider,
        repository: IssueRepository | None = None,
    ) -> None:
        self.provider = provider
        self.repository = repository or IssueRepository()

    def request_advice(
        self,
        issues_path: Path,
        advice_path: Path,
        *,
        issue_id: str,
        project_id: str,
        context_fragments: list[str] | None = None,
        force_refresh: bool = False,
    ) -> AdviceResult:
        stored = self.repository.load_advice(advice_path)
        cached = (stored.get("items") or {}).get(issue_id)
        if cached and not force_refresh:
            return AdviceResult.model_validate(cached["result"])
        issue = _find_issue(self.repository.load_issues(issues_path), issue_id)
        if issue.status == IssueStatus.IGNORED:
            raise IgnoredIssueIsImmutableError("ignored issue cannot request advice")
        result = self.provider.generate_advice(
            AdviceRequest(
                project_id=project_id,
                issue=issue,
                context_fragments=context_fragments or [],
            )
        )
        stored.setdefault("schema_version", "1.0")
        stored.setdefault("items", {})[issue_id] = {
            "generated_at": utc_now().isoformat(),
            "result": result.model_dump(mode="json"),
        }
        self.repository.save_advice(advice_path, stored)
        return result
