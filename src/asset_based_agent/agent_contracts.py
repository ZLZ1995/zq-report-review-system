"""Shared, data-only understanding protocol; decisions are not authorizations."""
from __future__ import annotations

import json
import re
from typing import Annotated, Literal
from urllib.parse import urlsplit

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_serializer,
    model_validator,
)

Identifier = Annotated[str, Field(min_length=1, max_length=128, pattern=r'^\S+$')]
ShortText = Annotated[str, Field(min_length=1, max_length=1000)]
MessageIntent = Literal['consult', 'execute', 'clarify', 'cancel', 'unsupported']
UnderstandingDecision = Literal['answer', 'ask', 'plan', 'browser', 'cancel', 'refuse']
Adapter = Literal['report.review', 'review.preflight', 'valuation-detail-workbook-fill',
                  'gongshang-change-history-docx', 'financial-brief-docx',
                  'office-workflow-to-skill', 'browser.task']


class Record(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True, frozen=True)


class Versioned(Record):
    schema_version: Literal[1] = 1

    @field_validator('schema_version', mode='before')
    @classmethod
    def integer_version(cls, value):
        if type(value) is not int:
            raise ValueError('Invalid schema version')
        return value


class EvidenceRef(Record):
    id: Identifier
    name: str = Field(min_length=1, max_length=255, pattern=r'^[^/\\\x00]+$')
    sha256: str = Field(pattern=r'^[0-9a-f]{64}$')


class MessageRef(Record):
    id: Identifier
    role: Literal['user', 'assistant']
    text: str = Field(min_length=1, max_length=12000)


class SkillCandidate(Record):
    id: Identifier
    name: str = Field(min_length=1, max_length=200)
    adapter: Adapter
    description: str = Field(max_length=1000)


class UnderstandingRequest(Versioned):
    request_id: Identifier
    model_id: Identifier
    message_id: Identifier
    prompt: str = Field(min_length=1, max_length=12000)
    files: list[EvidenceRef] = Field(default_factory=list, max_length=100)
    skills: list[SkillCandidate] = Field(default_factory=list, max_length=32)
    context: list[MessageRef] = Field(default_factory=list, max_length=10)

    @model_validator(mode='after')
    def bounded_unique(self):
        for items in (self.files, self.skills, self.context):
            if len({item.id for item in items}) != len(items):
                raise ValueError('Duplicate context identifiers')
        if self.message_id in {item.id for item in self.context}:
            raise ValueError('Current message must not occur in history')
        if not self.prompt.strip() or len(self.model_dump_json().encode('utf-8')) > 64000:
            raise ValueError('Understanding request exceeds bounds')
        return self


class MissingInput(Record):
    field: Literal['goal', 'targets', 'references', 'skill', 'constraint', 'authorization']
    question: ShortText


class BrowserIntent(Record):
    """Proposed website scope, never permission or browser credentials."""
    origins: list[str] = Field(min_length=1, max_length=20)
    actions: list[Literal['observe', 'navigate', 'click', 'fill', 'select', 'login', 'scroll', 'wait', 'download', 'upload']] = Field(min_length=1, max_length=10)

    @model_validator(mode='after')
    def exact_origins(self):
        if len(set(self.origins)) != len(self.origins) or len(set(self.actions)) != len(self.actions):
            raise ValueError('Duplicate browser scope')
        for origin in self.origins:
            parsed = urlsplit(origin)
            host = parsed.hostname or ''
            canonical_host = f'[{host}]' if ':' in host else host
            canonical = 'https://' + canonical_host + (f':{parsed.port}' if parsed.port else '')
            if (len(origin) > 2048 or not origin.isascii() or any(c.isspace() or ord(c) < 32 for c in origin)
                    or '\\' in origin or parsed.scheme != 'https' or not parsed.hostname
                    or parsed.username is not None or parsed.password is not None
                    or parsed.path or parsed.query or parsed.fragment or parsed.port == 443
                    or origin != canonical or (':' not in host and
                        not all(re.fullmatch(r'[a-z0-9](?:[a-z0-9-]*[a-z0-9])?', label)
                                for label in host.split('.')))):
                raise ValueError('Browser intent requires canonical HTTPS origins')
        return self


class TaskUnderstanding(Versioned):
    browser: BrowserIntent | None = None
    message_intent: MessageIntent
    goal: str = Field(max_length=2000)
    targets: list[Identifier] = Field(max_length=100)
    references: list[Identifier] = Field(max_length=100)
    excluded: list[Identifier] = Field(max_length=100)
    constraints: list[ShortText] = Field(max_length=20)
    deliverables: list[ShortText] = Field(max_length=20)
    missing_inputs: list[MissingInput] = Field(max_length=10)
    evidence_message_ids: list[Identifier] = Field(min_length=1, max_length=11)
    skill_ids: list[Identifier] = Field(max_length=8)
    next_action: UnderstandingDecision
    reply: str = Field(min_length=1, max_length=4000)

    @model_validator(mode='after')
    def coherent(self):
        all_files = self.targets + self.references + self.excluded
        if len(set(all_files)) != len(all_files):
            raise ValueError('File roles overlap or contain duplicates')
        for ids in (self.skill_ids, self.evidence_message_ids):
            if len(set(ids)) != len(ids):
                raise ValueError('Duplicate decision identifiers')
        allowed = {'consult': {'answer', 'ask'}, 'execute': {'plan', 'browser', 'ask', 'refuse'},
                   'clarify': {'ask'}, 'cancel': {'cancel'}, 'unsupported': {'refuse', 'ask'}}
        if self.next_action not in allowed[self.message_intent]:
            raise ValueError('Intent and decision disagree')
        if self.next_action == 'browser':
            if (self.browser is None or self.skill_ids != ['browser.task'] or not self.goal.strip()
                    or self.targets or self.references or self.missing_inputs):
                raise ValueError('Incomplete or mixed browser execution proposal')
        elif self.browser is not None:
            raise ValueError('Browser scope cannot accompany another decision')
        if self.next_action == 'plan':
            if not self.goal.strip() or not self.skill_ids or self.missing_inputs:
                raise ValueError('Incomplete understanding cannot plan execution')
        elif self.next_action != 'browser' and self.skill_ids:
            raise ValueError('Non-execution decision must not schedule skills')
        if self.next_action == 'ask' and not self.missing_inputs:
            raise ValueError('Clarification must identify missing input')
        if not self.reply.strip():
            raise ValueError('Reply cannot be blank')
        return self

    @model_serializer(mode='wrap')
    def legacy_shape(self, handler):
        result = handler(self)
        if self.browser is None:
            result.pop('browser', None)
        return result


class ProposedInput(Record):
    kind: Literal['file', 'step_output']
    ref: Identifier
    role: Literal['target', 'reference']


class ProposedStep(Record):
    step_id: Identifier
    skill_id: Identifier
    goal: ShortText
    inputs: list[ProposedInput] = Field(min_length=1, max_length=100)
    dependencies: list[Identifier] = Field(max_length=32)


class PlanProposal(Versioned):
    """Untrusted model proposal; contains no code, paths, versions or grants."""
    request_id: Identifier
    steps: list[ProposedStep] = Field(min_length=1, max_length=32)


def validate_understanding(request: UnderstandingRequest, result: TaskUnderstanding):
    """Apply in server and client; a valid result still requires local permissions."""
    file_ids = {f.id for f in request.files}
    if not set(result.targets + result.references + result.excluded) <= file_ids:
        raise ValueError('Unknown file reference')
    if not set(result.skill_ids) <= {s.id for s in request.skills}:
        raise ValueError('Unknown skill')
    browser_candidates = [s for s in request.skills if s.adapter == 'browser.task']
    if result.next_action == 'browser' and not any(s.id == 'browser.task' for s in browser_candidates):
        raise ValueError('Client has not enabled browser tasks')
    if result.next_action == 'plan' and any(s.id in result.skill_ids for s in browser_candidates):
        raise ValueError('Browser capability cannot use file planning')
    if not set(result.evidence_message_ids) <= {request.message_id, *(m.id for m in request.context)}:
        raise ValueError('Unknown source message')
    if request.message_id not in result.evidence_message_ids:
        raise ValueError('Current message must inform the decision')
    if result.next_action == 'plan' and not result.targets:
        raise ValueError('Current file-based executors require targets')
    if len(json.dumps(result.model_dump(), ensure_ascii=False).encode('utf-8')) > 64000:
        raise ValueError('Understanding result exceeds bounds')
    return result


class PlanningRequest(Versioned):
    request: UnderstandingRequest
    understanding: TaskUnderstanding

    @model_validator(mode='after')
    def executable_understanding(self):
        validate_understanding(self.request, self.understanding)
        if self.understanding.next_action != 'plan':
            raise ValueError('Only complete execution understanding can request a plan')
        if len(self.model_dump_json().encode('utf-8')) > 96000:
            raise ValueError('Planning request exceeds bounds')
        return self


def validate_proposal(request: PlanningRequest, proposal: PlanProposal):
    """Shared structural boundary; local compilation adds capability/type checks."""
    request = PlanningRequest.model_validate(request.model_dump())
    proposal = PlanProposal.model_validate(proposal.model_dump())
    understanding = request.understanding
    if proposal.request_id != request.request.request_id:
        raise ValueError('Plan request identity mismatch')
    if {s.skill_id for s in proposal.steps} != set(understanding.skill_ids):
        raise ValueError('Plan does not cover the understood skills')
    by_id = {s.step_id: s for s in proposal.steps}
    if len(by_id) != len(proposal.steps):
        raise ValueError('Duplicate plan step')
    for step in proposal.steps:
        if (not step.goal.strip() or not set(step.dependencies) <= set(by_id)
                or len(set(step.dependencies)) != len(step.dependencies) or step.step_id in step.dependencies):
            raise ValueError('Invalid step goal or dependencies')
    completed: set[str] = set()
    while len(completed) != len(by_id):
        ready = {s.step_id for s in proposal.steps if s.step_id not in completed
                 and set(s.dependencies) <= completed}
        if not ready:
            raise ValueError('Plan dependency cycle')
        completed.update(ready)
    used = set()
    selected = set(understanding.targets + understanding.references)
    for step in proposal.steps:
        ancestors, pending = set(), list(step.dependencies)
        while pending:
            parent = pending.pop()
            if parent not in ancestors:
                ancestors.add(parent)
                pending.extend(by_id[parent].dependencies)
        if not any(i.role == 'target' for i in step.inputs):
            raise ValueError('Step has no target')
        if len({(i.kind, i.ref) for i in step.inputs}) != len(step.inputs):
            raise ValueError('Duplicate step input')
        for item in step.inputs:
            if item.kind == 'file':
                if (item.ref not in selected or
                        (item.role == 'target') != (item.ref in understanding.targets)):
                    raise ValueError('Plan input is outside the understood role or scope')
                used.add(item.ref)
            elif item.ref not in ancestors:
                raise ValueError('Output input has no producing ancestor')
    if used != selected or len(proposal.model_dump_json().encode('utf-8')) > 64000:
        raise ValueError('Plan is incomplete or exceeds bounds')
    return proposal
