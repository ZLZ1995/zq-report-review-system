"""Persisted domain models for projects, rounds, files, and review issues."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .enums import FileRole, IssueStatus, ProjectStatus, RiskLevel, RoundStatus


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class PersistedModel(BaseModel):
    model_config = ConfigDict(extra="ignore", use_enum_values=False)


class SourceFile(PersistedModel):
    file_id: str
    original_name: str
    extension: str
    sha256: str
    size_bytes: int = Field(ge=0)
    role: FileRole = FileRole.UNKNOWN
    round_number: int = Field(ge=1)
    original_path: str
    normalized_path: str | None = None
    replaces_file_id: str | None = None
    extraction_status: str = "pending"
    ocr_status: str = "not_required"


class IssueLocation(PersistedModel):
    chapter: str | None = None
    page: int | None = Field(default=None, ge=1)
    paragraph: int | None = Field(default=None, ge=1)
    table: str | None = None
    cell: str | None = None


class IssueEvidence(PersistedModel):
    evidence_type: str
    source_file_id: str
    summary: str
    location: IssueLocation | None = None


class IssueHistoryEntry(PersistedModel):
    round_number: int = Field(ge=1)
    status: IssueStatus
    recorded_at: datetime = Field(default_factory=utc_now)
    note: str = ""


class ReviewIssue(PersistedModel):
    issue_id: str
    fingerprint: str
    source_file_id: str
    source_file_name: str
    category: str
    risk_level: RiskLevel
    status: IssueStatus
    location: IssueLocation
    original_text: str = ""
    description: str
    evidence: list[IssueEvidence] = Field(default_factory=list)
    recommendation: str = ""
    confidence: float = Field(ge=0.0, le=1.0)
    first_seen_round: int = Field(ge=1)
    last_seen_round: int = Field(ge=1)
    ignored: bool = False
    ignored_at: datetime | None = None
    ignored_by: str | None = None
    history: list[IssueHistoryEntry] = Field(default_factory=list)
    origin: str = ""
    rule_id: str = ""
    validation_status: str = "accepted"
    evidence_state: str = "sufficient"
    occurrences: list[IssueLocation] = Field(default_factory=list)
    impact_path: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_rounds_and_ignore_state(self) -> ReviewIssue:
        if self.last_seen_round < self.first_seen_round:
            raise ValueError("last_seen_round cannot be earlier than first_seen_round")
        if self.status == IssueStatus.IGNORED and not self.ignored:
            raise ValueError("ignored status requires ignored=true")
        if self.ignored and self.status != IssueStatus.IGNORED:
            raise ValueError("ignored=true requires ignored status")
        return self


class AuditRound(PersistedModel):
    round_id: str
    round_number: int = Field(ge=1)
    status: RoundStatus = RoundStatus.DRAFT
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    source_file_ids: list[str] = Field(default_factory=list)
    issue_count: int = Field(default=0, ge=0)
    progress_path: str
    issues_path: str
    error_snapshot_path: str


class AuditProject(PersistedModel):
    schema_version: str = "1.0"
    project_id: str
    name: str = Field(min_length=1)
    project_path: str
    status: ProjectStatus = ProjectStatus.DRAFT
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    current_round: int = Field(default=0, ge=0)
    files: list[SourceFile] = Field(default_factory=list)
    rounds: list[AuditRound] = Field(default_factory=list)
    final_report_path: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
