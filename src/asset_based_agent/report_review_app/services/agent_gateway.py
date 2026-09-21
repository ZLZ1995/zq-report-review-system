"""Read-only boundary between the desktop workflow and review agents."""

from __future__ import annotations

from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

from ..domain.models import ReviewIssue, SourceFile


class GatewayModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ReviewRoundRequest(GatewayModel):
    project_id: str
    round_number: int = Field(ge=1)
    files: list[SourceFile]
    previous_issues: list[ReviewIssue] = Field(default_factory=list)


class ReviewRoundResult(GatewayModel):
    project_id: str
    round_number: int = Field(ge=1)
    issues: list[ReviewIssue]
    source_hashes_unchanged: bool


class AdviceRequest(GatewayModel):
    project_id: str
    issue: ReviewIssue
    context_fragments: list[str] = Field(default_factory=list)


class AdviceResult(GatewayModel):
    issue_id: str
    explanation: str
    checks: list[str] = Field(default_factory=list)
    suggested_revision: str = ""


class ConversationMessage(GatewayModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=4_000)
    created_at: str


class ConversationTurnRequest(GatewayModel):
    project_id: str
    issue: ReviewIssue
    advice: AdviceResult | None = None
    messages: list[ConversationMessage] = Field(default_factory=list)
    user_message: str = Field(min_length=1, max_length=4_000)


class ConversationTurnResult(GatewayModel):
    reply: str = Field(min_length=1, max_length=20_000)


class ReadOnlyAgentGateway(Protocol):
    """Interface intentionally omitting every document write operation."""

    def review_round(self, request: ReviewRoundRequest) -> ReviewRoundResult:
        ...

    def request_advice(self, request: AdviceRequest) -> AdviceResult:
        ...

    def continue_conversation(
        self,
        request: ConversationTurnRequest,
    ) -> ConversationTurnResult:
        ...
