"""Dedicated agent profiles: role-scoped context, tools and verification.

Each of the eight roles has an explicit contract: what context it may read,
which tools it may call, which data it is forbidden to touch, its model
policy, output schema and budget. Execution and acceptance are separated:
the Independent Verifier is strictly read-only over artifacts and evidence.
Agents are only split for file-group parallelism, independent verification,
multiple artifacts or context overflow — never for a simple task.
"""
from __future__ import annotations

from typing import Literal

from pydantic import Field

from ..agent_contracts import Identifier, Record

AgentRole = Literal['conversation', 'intent_analyst', 'capability_router',
                    'plan_compiler', 'domain_executor', 'independent_verifier',
                    'memory_curator', 'browser_operator']

ModelPolicy = Literal['fast', 'standard', 'strong']

SplitReason = Literal['file_group_parallel', 'independent_verification',
                      'multi_artifact', 'context_overflow']

FailureKind = Literal['formula', 'layout', 'hash', 'template', 'receipt']

MAX_PROFILE_TOKEN_BUDGET = 200_000


class AgentProfile(Record):
    role: AgentRole
    readable_context: tuple[str, ...] = Field(min_length=1)
    allowed_tools: tuple[str, ...] = ()
    forbidden_data: tuple[str, ...] = ()
    model_policy: ModelPolicy = 'standard'
    output_schema: str = Field(min_length=1, max_length=128)
    token_budget: int = Field(ge=1, le=MAX_PROFILE_TOKEN_BUDGET)
    max_parallel: int = Field(default=1, ge=1, le=8)
    requires_page_lease: bool = False


PROFILES: tuple[AgentProfile, ...] = (
    AgentProfile(
        role='conversation',
        readable_context=('conversation', 'turn_envelope', 'task_panel'),
        allowed_tools=('deliver_message',),
        model_policy='fast',
        output_schema='ConversationReply',
        token_budget=8_000),
    AgentProfile(
        role='intent_analyst',
        readable_context=('conversation', 'turn_envelope', 'attachment_manifest'),
        model_policy='standard',
        output_schema='AdjudicatedIntent',
        token_budget=16_000),
    AgentProfile(
        role='capability_router',
        readable_context=('turn_envelope', 'skill_manifest', 'capability_matrix'),
        model_policy='fast',
        output_schema='CapabilityDecision',
        token_budget=8_000),
    AgentProfile(
        role='plan_compiler',
        readable_context=('turn_envelope', 'attachment_manifest', 'skill_manifest'),
        model_policy='strong',
        output_schema='WorkflowPlan',
        token_budget=32_000),
    AgentProfile(
        role='domain_executor',
        readable_context=('turn_envelope', 'attachment_manifest', 'evidence'),
        allowed_tools=('run_skill', 'read_attachment', 'write_workspace'),
        forbidden_data=('credential_plaintext', 'memory_store'),
        model_policy='standard',
        output_schema='ArtifactClaim',
        token_budget=120_000,
        max_parallel=4),
    AgentProfile(
        role='independent_verifier',
        readable_context=('artifact', 'evidence'),
        allowed_tools=(),
        forbidden_data=('artifact_write', 'business_file_write',
                        'credential_plaintext', 'memory_store'),
        model_policy='standard',
        output_schema='VerificationReport',
        token_budget=16_000),
    AgentProfile(
        role='memory_curator',
        readable_context=('memory_candidates', 'memory_store'),
        allowed_tools=('memory_write',),
        forbidden_data=('business_file_write', 'credential_plaintext',
                        'artifact_write'),
        model_policy='fast',
        output_schema='MemoryWriteSet',
        token_budget=8_000),
    AgentProfile(
        role='browser_operator',
        readable_context=('turn_envelope', 'page_origin', 'page_snapshot'),
        allowed_tools=('browser_navigate', 'browser_fill', 'browser_click',
                       'browser_download', 'browser_upload'),
        forbidden_data=('credential_plaintext', 'memory_store',
                        'business_file_write'),
        model_policy='standard',
        output_schema='BrowserActionReceipt',
        token_budget=24_000,
        requires_page_lease=True),
)

_BY_ROLE: dict[str, AgentProfile] = {profile.role: profile for profile in PROFILES}


def profile_for(role: str) -> AgentProfile:
    return _BY_ROLE[role]


def allows_tool(profile: AgentProfile, tool: str) -> bool:
    return tool in profile.allowed_tools


def allows_context(profile: AgentProfile, section: str) -> bool:
    return (section in profile.readable_context
            and section not in profile.forbidden_data)


class SplitDecision(Record):
    split: bool
    reasons: tuple[SplitReason, ...] = ()


def should_split_agents(*, file_groups: int = 1,
                        needs_independent_verification: bool = False,
                        artifact_count: int = 1,
                        context_overflow: bool = False) -> SplitDecision:
    reasons: list[SplitReason] = []
    if file_groups > 1:
        reasons.append('file_group_parallel')
    if needs_independent_verification:
        reasons.append('independent_verification')
    if artifact_count > 1:
        reasons.append('multi_artifact')
    if context_overflow:
        reasons.append('context_overflow')
    return SplitDecision(split=bool(reasons), reasons=tuple(reasons))


class ArtifactClaim(Record):
    artifact_id: Identifier
    sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    template_id: str | None = None
    formulas: tuple[str, ...] = ()
    layout: dict[str, str] = Field(default_factory=dict)
    receipt: dict[str, str] = Field(default_factory=dict)


class ExpectedArtifact(Record):
    sha256: str | None = Field(default=None, pattern=r'^[0-9a-f]{64}$')
    template_id: str | None = None
    formulas: tuple[str, ...] | None = None
    layout: dict[str, str] | None = None
    receipt_fields: tuple[str, ...] | None = None


class VerificationFailure(Record):
    kind: FailureKind
    detail: str = Field(min_length=1, max_length=500)


class VerificationReport(Record):
    artifact_id: Identifier
    verifier_role: Literal['independent_verifier'] = 'independent_verifier'
    passed: bool
    failures: tuple[VerificationFailure, ...] = ()


def verify_artifact(claim: ArtifactClaim,
                    expected: ExpectedArtifact) -> VerificationReport:
    failures: list[VerificationFailure] = []
    if expected.sha256 is not None and claim.sha256 != expected.sha256:
        failures.append(VerificationFailure(
            kind='hash', detail='Artifact hash does not match expectation'))
    if expected.template_id is not None and claim.template_id != expected.template_id:
        failures.append(VerificationFailure(
            kind='template', detail='Artifact template does not match expectation'))
    if expected.formulas is not None:
        missing = [f for f in expected.formulas if f not in claim.formulas]
        if missing:
            failures.append(VerificationFailure(
                kind='formula',
                detail=f'Missing or altered formulas: {missing}'))
    if expected.layout is not None:
        mismatched = [key for key, value in expected.layout.items()
                      if claim.layout.get(key) != value]
        if mismatched:
            failures.append(VerificationFailure(
                kind='layout',
                detail=f'Layout mismatch on: {mismatched}'))
    if expected.receipt_fields is not None:
        missing = [key for key in expected.receipt_fields
                   if not claim.receipt.get(key)]
        if missing:
            failures.append(VerificationFailure(
                kind='receipt',
                detail=f'Receipt missing fields: {missing}'))
    return VerificationReport(artifact_id=claim.artifact_id,
                              passed=not failures,
                              failures=tuple(failures))
