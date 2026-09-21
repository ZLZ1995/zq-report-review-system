"""Immutable per-turn snapshot; the only input to understanding and planning.

An envelope is evidence, not authority: it freezes what the user asked and
which attachment versions were selected this turn. Execution still requires
the existing permission receipts bound to the task snapshot.
"""
from __future__ import annotations

import json
from datetime import datetime
from hashlib import sha256
from typing import Literal

from pydantic import Field, field_validator, model_validator

from ..agent_contracts import Identifier, Record
from .agent_permission_modes import validate_permission_mode


class AttachmentVersion(Record):
    id: Identifier
    name: str = Field(min_length=1, max_length=255, pattern=r'^[^/\\\x00]+$')
    sha256: str = Field(pattern=r'^[0-9a-f]{64}$')


class TurnEnvelope(Record):
    schema_version: Literal[1] = 1
    owner: Identifier
    project_id: Identifier
    session_id: Identifier
    turn_id: Identifier
    message_id: Identifier
    raw_user_text: str = Field(min_length=1, max_length=12000)
    normalized_text: str = Field(min_length=1, max_length=12000)
    explicit_references: tuple[str, ...] = ()
    selected_attachment_versions: tuple[AttachmentVersion, ...] = Field(default=(), max_length=100)
    newly_attached_ids: tuple[Identifier, ...] = ()
    historical_reference_ids: tuple[Identifier, ...] = ()
    excluded_attachment_ids: tuple[Identifier, ...] = ()
    active_model_id: Identifier
    permission_mode: str
    browser_page_identity: str | None = None
    locale: str = Field(min_length=1, max_length=35)
    timezone: str = Field(min_length=1, max_length=64)
    submitted_at: str
    prior_clarification_chain: tuple[str, ...] = Field(default=(), max_length=20)

    @field_validator('schema_version', mode='before')
    @classmethod
    def integer_version(cls, value):
        if type(value) is not int:
            raise ValueError('Invalid schema version')
        return value

    @field_validator('owner', 'project_id', 'session_id', 'turn_id', 'message_id',
                     'active_model_id', mode='after')
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError('Turn identity must be nonblank')
        return value

    @field_validator('permission_mode', mode='after')
    @classmethod
    def known_mode(cls, value):
        return validate_permission_mode(value)

    @field_validator('submitted_at', mode='after')
    @classmethod
    def parseable_time(cls, value):
        if not isinstance(value, str):
            raise ValueError('Invalid submission time')  # noqa: TRY004 - pydantic validator
        datetime.fromisoformat(value)
        return value

    @field_validator('raw_user_text', 'normalized_text', mode='after')
    @classmethod
    def nonblank_text(cls, value):
        if not value.strip():
            raise ValueError('本轮要求不能为空')
        return value

    @model_validator(mode='after')
    def disjoint_scope(self):
        selected = tuple(item.id for item in self.selected_attachment_versions)
        if len(set(selected)) != len(selected):
            raise ValueError('Duplicate selected attachment')
        selected_set = set(selected)
        if not set(self.newly_attached_ids) <= selected_set:
            raise ValueError('Newly attached files must be selected this turn')
        if selected_set & set(self.excluded_attachment_ids):
            raise ValueError('Excluded attachments overlap the selection')
        if selected_set & set(self.historical_reference_ids):
            raise ValueError('Historical references overlap the selection')
        return self


def envelope_hash(envelope: TurnEnvelope) -> str:
    envelope = TurnEnvelope.model_validate(envelope.model_dump())
    payload = json.dumps(envelope.model_dump(), sort_keys=True, ensure_ascii=False,
                         allow_nan=False)
    return sha256(payload.encode('utf-8')).hexdigest()
