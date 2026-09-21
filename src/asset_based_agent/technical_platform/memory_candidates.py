"""Memory candidate extraction: provenance, sensitivity and a state machine.

Candidates are proposals, never facts. Sensitive content (passwords, ID
numbers, bank cards, keys, cookies, tokens) is flagged at extraction time and
can never be written. States: proposed / confirmed / revoked / superseded.
"""
from __future__ import annotations

import re
from datetime import datetime
from hashlib import sha256
from typing import Literal

from pydantic import Field, field_validator

from ..agent_contracts import Identifier, Record
from .turn_normalizer import normalize_text

CATEGORIES = ('user', 'feedback', 'project', 'reference',
              'runtime_summary', 'runtime_task', 'runtime_clarification',
              'runtime_receipt', 'skill_miss', 'skill_false_positive',
              'skill_acceptance', 'skill_rule_suggestion')

Category = Literal['user', 'feedback', 'project', 'reference',
                   'runtime_summary', 'runtime_task', 'runtime_clarification',
                   'runtime_receipt', 'skill_miss', 'skill_false_positive',
                   'skill_acceptance', 'skill_rule_suggestion']
MemoryStatus = Literal['proposed', 'confirmed', 'revoked', 'superseded']

_REMEMBER = re.compile(r'^记住[，,]?(?P<text>.+)$')
_SENSITIVE = re.compile(r'密码|口令|身份证|银行卡|卡号|api[-_ ]?key|cookie|token|secret|jwt')
_TRANSITIONS = {('proposed', 'confirmed'), ('proposed', 'revoked'),
                ('confirmed', 'revoked'), ('confirmed', 'superseded')}


class MemoryCandidate(Record):
    schema_version: Literal[1] = 1
    id: Identifier
    category: Category
    key: str = Field(min_length=1, max_length=128)
    text: str = Field(min_length=1, max_length=2000)
    source_message_id: Identifier | None = None
    source_task_id: Identifier | None = None
    status: MemoryStatus = 'proposed'
    sensitivity: Literal['normal', 'sensitive'] = 'normal'
    auto_confirmable: bool = False
    confidence: float = Field(gt=0, le=1)
    verification_policy: str = Field(min_length=1, max_length=64)
    proposed_at: str
    version: int = Field(default=1, ge=1)

    @field_validator('schema_version', mode='before')
    @classmethod
    def integer_version(cls, value):
        if type(value) is not int:
            raise ValueError('Invalid schema version')
        return value

    @field_validator('proposed_at', mode='after')
    @classmethod
    def parseable_time(cls, value):
        datetime.fromisoformat(value)
        return value


def scan_sensitive(text: str) -> bool:
    return bool(_SENSITIVE.search(text.casefold()))


def validate_transition(old: str, new: str) -> bool:
    return (old, new) in _TRANSITIONS


def _policy_for(category: str) -> str:
    if category in ('user', 'feedback'):
        return 'explicit_user'
    if category == 'project':
        return 'requires_user_confirmation'
    if category == 'reference':
        return 'source_evidence'
    return 'runtime_trace'


def extract_candidates(messages, *, now: str, category_hint=None) -> list[MemoryCandidate]:
    """Rule-based extraction from newly finished user messages only."""
    datetime.fromisoformat(now)
    candidates = []
    for message in messages:
        if message.get('role') != 'user':
            continue
        text = normalize_text(message['text'])
        category, body, confidence = None, None, 0.0
        if category_hint is not None:
            if category_hint not in CATEGORIES:
                raise ValueError('未知的记忆类别')
            category, body, confidence = category_hint, text, 0.7
        else:
            matched = _REMEMBER.match(text)
            if matched:
                category, body, confidence = 'user', matched.group('text').strip(), 0.9
        if category is None or not body:
            continue
        sensitive = scan_sensitive(body)
        identity = 'cand-' + sha256(
            (message['id'] + '\0' + body).encode('utf-8')).hexdigest()[:16]
        candidates.append(MemoryCandidate(
            id=identity, category=category,
            key=f'{category}:{sha256(body.encode("utf-8")).hexdigest()[:8]}',
            text=body, source_message_id=message['id'],
            sensitivity='sensitive' if sensitive else 'normal',
            auto_confirmable=category in ('user', 'feedback') and not sensitive,
            confidence=confidence, verification_policy=_policy_for(category),
            proposed_at=now))
    return candidates
