"""Public API request and response contracts."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)
    client_instance_id: str = Field(min_length=1, max_length=128)


class RefreshRequest(BaseModel):
    refresh_token: str = Field(min_length=32, max_length=512)


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=8, max_length=256)


class CreateUserRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    display_name: str = Field(min_length=1, max_length=128)
    temporary_password: str = Field(min_length=8, max_length=16)
    email: str | None = Field(default=None, max_length=320)


class ResetPasswordRequest(BaseModel):
    temporary_password: str = Field(min_length=8, max_length=256)


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    user_id: str
    username: str
    display_name: str
    role: str
    status: str
    must_change_password: bool


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserResponse


class BalanceAdjustmentRequest(BaseModel):
    amount: Decimal


class BalanceResponse(BaseModel):
    balance: str
    currency: str = "CNY"


class ModelCreateRequest(BaseModel):
    code: str = Field(min_length=1, max_length=64)
    display_name: str = Field(min_length=1, max_length=128)
    tier: str = Field(min_length=1, max_length=24)
    model_multiplier: Decimal = Field(gt=0)
    max_output_tokens: int = Field(ge=1, le=1_000_000)


class ModelAdminResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    model_id: str
    code: str
    display_name: str
    tier: str
    enabled: bool
    model_multiplier: Decimal
    max_output_tokens: int


class PublicModelResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    model_id: str
    code: str
    display_name: str
    tier: str


class TokenRatesRequest(BaseModel):
    input: Decimal = Field(ge=0)
    output: Decimal = Field(ge=0)
    cache_hit: Decimal = Field(ge=0)
    cache_miss: Decimal = Field(ge=0)
    reasoning: Decimal = Field(ge=0)


class ProviderRouteCreateRequest(BaseModel):
    provider_type: str = Field(pattern="^(deepseek|openai_compatible)$")
    provider_model: str = Field(min_length=1, max_length=128)
    base_url: str = Field(pattern="^https://", max_length=512)
    api_key: str = Field(min_length=1, max_length=4096)
    priority: int = Field(ge=1, le=10_000)
    timeout_seconds: int = Field(default=90, ge=10, le=600)
    rates: TokenRatesRequest


class ProviderRouteResponse(BaseModel):
    route_id: str
    model_id: str
    provider_type: str
    provider_model: str
    base_url: str
    priority: int
    enabled: bool
    api_key_configured: bool = True


class BillingMultiplierRequest(BaseModel):
    multiplier: Decimal = Field(gt=0)


class ReviewLocationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    chapter: str | None = Field(default=None, max_length=256)
    page: int | None = Field(default=None, ge=1)
    paragraph: int | None = Field(default=None, ge=1)
    table: str | None = Field(default=None, max_length=256)
    cell: str | None = Field(default=None, max_length=64)
    sheet: str | None = Field(default=None, max_length=255)


class ReviewChunkRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    chunk_id: str = Field(min_length=1, max_length=128)
    source_file_id: str = Field(min_length=1, max_length=128)
    source_file_name: str = Field(min_length=1, max_length=512)
    file_type: Literal["word", "excel", "pdf"]
    role: str = Field(min_length=1, max_length=64)
    text: str = Field(min_length=1, max_length=12_000)
    location: ReviewLocationRequest = Field(default_factory=ReviewLocationRequest)
    reference_only: bool = False
    sheet_name: str | None = Field(default=None, max_length=255)
    sheet_state: Literal["visible"] = "visible"

    @field_validator("source_file_name")
    @classmethod
    def reject_local_path(cls, value: str) -> str:
        if "/" in value or "\\" in value:
            raise ValueError("source_file_name must be a basename")
        return value

    @model_validator(mode="after")
    def validate_sheet_identity(self) -> ReviewChunkRequest:
        if self.file_type == "excel":
            if not self.sheet_name:
                raise ValueError("Excel chunks require sheet_name")
            if self.location.sheet and self.location.sheet != self.sheet_name:
                raise ValueError("location.sheet must match sheet_name")
        elif self.sheet_name or self.location.sheet:
            raise ValueError("only Excel chunks may identify a sheet")
        return self


class ReviewJobCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    skill_instructions: str = Field(default="", max_length=12000)
    user_request: str = Field(default="", max_length=12000)

    client_job_id: str = Field(min_length=1, max_length=128)
    model_id: str = Field(min_length=1, max_length=36)
    round_number: int = Field(ge=1)
    chunks: list[ReviewChunkRequest] = Field(min_length=1, max_length=2_000)

    @model_validator(mode="after")
    def limit_total_context(self) -> ReviewJobCreateRequest:
        if sum(len(chunk.text) for chunk in self.chunks) > 2_000_000:
            raise ValueError("review context is too large")
        return self


class ReviewJobResponse(BaseModel):
    job_id: str
    client_job_id: str
    model_id: str
    round_number: int
    status: str
    batch_count: int
    completed_batches: int
    progress_percent: int
    event_sequence: int
    heartbeat_status: Literal["active", "stale", "not_applicable"]
    issues: list[dict[str, object]] = Field(default_factory=list)
    error_code: str | None = None


class ReviewJobEventResponse(BaseModel):
    sequence: int = Field(ge=1)
    kind: Literal[
        "queued", "execution_requested", "running", "progress",
        "cancel_requested", "cancelled", "failed", "succeeded", "recovered",
    ]
    completed_batches: int = Field(ge=0)
    created_at: datetime


class ClientReleaseCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    manifest: dict[str, object]


class ClientReleaseTransitionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["canary", "stable", "withdrawn"]


class ClientReleaseResponse(BaseModel):
    release_id: str
    version: str
    platform: str
    arch: str
    sequence: int
    status: str
    manifest_sha256: str


class SkillReleaseCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    skill_id: str = Field(pattern=r"^[a-z][a-z0-9]*(?:[.-][a-z0-9]+)*$", max_length=80)
    version: str = Field(pattern=r"^\d+\.\d+\.\d+$", max_length=32)
    package_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    schema_version: Literal[1] = 1
    adapter: Literal["report.review", "review.preflight"]
    capabilities: list[Literal["read_selected_files", "generate_artifacts"]] = Field(
        min_length=1, max_length=2
    )
    minimum_client_version: str = Field(pattern=r"^\d+\.\d+\.\d+$", max_length=32)
    evidence_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    test_report_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_capabilities(self) -> SkillReleaseCreateRequest:
        if len(set(self.capabilities)) != len(self.capabilities):
            raise ValueError("capabilities must be unique")
        allowed = ({"read_selected_files", "generate_artifacts"}
                   if self.adapter == "report.review" else {"read_selected_files"})
        if set(self.capabilities) > allowed or "read_selected_files" not in self.capabilities:
            raise ValueError("adapter capabilities are invalid")
        return self


class SkillReleaseTransitionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["approved", "stable", "withdrawn"]


class SkillReleaseResponse(BaseModel):
    release_id: str
    skill_id: str
    version: str
    package_sha256: str
    schema_version: int
    adapter: str
    capabilities: list[str]
    minimum_client_version: str
    status: str


class AgentCompletionMessage(BaseModel):
    """流式请求消息：纯文本内容；禁止文件路径/二进制等额外字段。"""

    model_config = ConfigDict(extra='forbid')

    role: Literal['system', 'user', 'assistant', 'tool']
    content: str = Field(min_length=0, max_length=200_000)


class AgentCompletionToolSpec(BaseModel):
    model_config = ConfigDict(extra='forbid')

    name: str = Field(min_length=1, max_length=128)
    description: str = Field(default='', max_length=2000)
    input_schema: dict


class AgentCompletionStreamRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')

    protocol_version: int
    client_version: str = Field(default='', max_length=64)
    model_id: str = Field(min_length=1, max_length=64)
    client_request_id: str = Field(min_length=8, max_length=128)
    messages: list[AgentCompletionMessage] = Field(min_length=1)
    tools: list[AgentCompletionToolSpec] = Field(default_factory=list)
    sampling: dict = Field(default_factory=dict)
