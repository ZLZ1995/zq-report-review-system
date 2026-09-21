"""Issue-scoped multi-turn conversation with local-only persistence."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from openpyxl import load_workbook

from ..domain.enums import IssueStatus
from ..domain.models import ReviewIssue, utc_now
from ..repositories.issue_repository import IssueRepository
from .agent_gateway import (
    AdviceResult,
    ConversationMessage,
    ConversationTurnRequest,
    ConversationTurnResult,
)
from .issue_service import IgnoredIssueIsImmutableError, _find_issue


class ConversationValidationError(ValueError):
    pass


class HiddenWorkbookContextError(ConversationValidationError):
    pass


class ConversationProvider(Protocol):
    def continue_conversation(
        self,
        request: ConversationTurnRequest,
    ) -> ConversationTurnResult:
        ...


class ConversationService:
    MAX_USER_TURNS = 20

    def __init__(
        self,
        provider: ConversationProvider,
        repository: IssueRepository | None = None,
    ) -> None:
        self.provider = provider
        self.repository = repository or IssueRepository()

    def load_messages(
        self,
        conversation_path: Path,
        *,
        issue_id: str,
    ) -> list[ConversationMessage]:
        payload = self.repository.load_conversations(conversation_path)
        item = (payload.get("items") or {}).get(issue_id) or {}
        return [
            ConversationMessage.model_validate(message)
            for message in item.get("messages") or []
        ]

    def continue_conversation(
        self,
        issues_path: Path,
        advice_path: Path,
        conversation_path: Path,
        *,
        issue_id: str,
        project_id: str,
        user_message: str,
        workbook_paths: list[Path],
    ) -> list[ConversationMessage]:
        normalized_message = user_message.strip()
        if not normalized_message:
            raise ConversationValidationError("请输入需要继续讨论的内容。")
        if len(normalized_message) > 4_000:
            raise ConversationValidationError("单次输入不能超过4000个字符。")

        issue = _find_issue(self.repository.load_issues(issues_path), issue_id)
        if issue.status == IssueStatus.IGNORED:
            raise IgnoredIssueIsImmutableError("已忽略的问题不能继续对话。")
        if _issue_depends_on_hidden_workbook(issue, workbook_paths):
            raise HiddenWorkbookContextError(
                "该问题涉及隐藏工作表，按照隔离规则不能进入大模型对话。"
            )

        messages = self.load_messages(
            conversation_path,
            issue_id=issue_id,
        )
        if sum(message.role == "user" for message in messages) >= self.MAX_USER_TURNS:
            raise ConversationValidationError(
                f"单个问题最多支持{self.MAX_USER_TURNS}轮对话。"
            )
        advice = _load_advice(self.repository, advice_path, issue_id)
        result = self.provider.continue_conversation(
            ConversationTurnRequest(
                project_id=project_id,
                issue=issue,
                advice=advice,
                messages=messages,
                user_message=normalized_message,
            )
        )
        now = utc_now().isoformat()
        messages.extend(
            [
                ConversationMessage(
                    role="user",
                    content=normalized_message,
                    created_at=now,
                ),
                ConversationMessage(
                    role="assistant",
                    content=result.reply.strip(),
                    created_at=utc_now().isoformat(),
                ),
            ]
        )
        payload = self.repository.load_conversations(conversation_path)
        payload.setdefault("schema_version", "1.0")
        payload.setdefault("items", {})[issue_id] = {
            "updated_at": utc_now().isoformat(),
            "messages": [message.model_dump(mode="json") for message in messages],
        }
        self.repository.save_conversations(conversation_path, payload)
        return messages

    def clear(
        self,
        conversation_path: Path,
        *,
        issue_id: str,
    ) -> None:
        payload = self.repository.load_conversations(conversation_path)
        items = payload.setdefault("items", {})
        items.pop(issue_id, None)
        self.repository.save_conversations(conversation_path, payload)


def _load_advice(
    repository: IssueRepository,
    advice_path: Path,
    issue_id: str,
) -> AdviceResult | None:
    item = (repository.load_advice(advice_path).get("items") or {}).get(issue_id)
    if not item:
        return None
    return AdviceResult.model_validate(item["result"])


def _issue_depends_on_hidden_workbook(
    issue: ReviewIssue,
    workbook_paths: list[Path],
) -> bool:
    if not issue.source_file_name.lower().endswith((".xlsx", ".xlsm")):
        return False
    hidden_names: set[str] = set()
    for path in workbook_paths:
        workbook = load_workbook(
            path,
            read_only=True,
            data_only=False,
            keep_vba=path.suffix.lower() == ".xlsm",
        )
        try:
            hidden_names.update(
                sheet.title
                for sheet in workbook.worksheets
                if sheet.sheet_state != "visible"
            )
        finally:
            workbook.close()
    if issue.location.table in hidden_names:
        return True
    evidence_text = " ".join(item.summary for item in issue.evidence)
    text = " ".join(
        [issue.original_text, issue.description, evidence_text]
    )
    return any(
        f"{name}!" in text
        or f"'{name.replace(chr(39), chr(39) * 2)}'!" in text
        for name in hidden_names
    )
