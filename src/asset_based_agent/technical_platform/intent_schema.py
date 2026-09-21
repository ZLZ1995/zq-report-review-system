"""Structured intent contracts for understanding v2.

Model output is data, not authority: the schema deliberately has no tool,
permission, path or credential fields, so a model response can never grant
itself capabilities. Local adjudication in `intent_policy` decides what may
execute.
"""
from __future__ import annotations

from typing import Literal

from pydantic import Field, field_validator

from ..agent_contracts import Identifier, Record

IntentKind = Literal['consult', 'execute', 'clarify', 'cancel', 'unsupported']
IntentAction = Literal['plan', 'ask', 'answer', 'browser', 'cancel', 'refuse']


class SchemaV1(Record):
    schema_version: Literal[1] = 1

    @field_validator('schema_version', mode='before')
    @classmethod
    def integer_version(cls, value):
        if type(value) is not int:
            raise ValueError('Invalid schema version')
        return value


class ParsedSignals(SchemaV1):
    """Deterministic pre-parse output; no model involved."""

    actions: tuple[str, ...] = ()
    file_mentions: tuple[str, ...] = ()
    negated_mentions: tuple[str, ...] = ()
    quantities: tuple[str, ...] = ()
    time_hints: tuple[str, ...] = ()
    conditions: tuple[str, ...] = ()
    deliverable_formats: tuple[str, ...] = ()
    cancellation: bool = False
    authorization_claim: bool = False
    risk_hints: tuple[str, ...] = ()


class ModelIntent(SchemaV1):
    """Strict structured understanding returned by the model."""

    intent: IntentKind
    goal: str = Field(max_length=2000)
    targets: tuple[str, ...] = Field(default=(), max_length=100)
    references: tuple[str, ...] = Field(default=(), max_length=100)
    excluded_inputs: tuple[str, ...] = Field(default=(), max_length=100)
    deliverables: tuple[str, ...] = Field(default=(), max_length=20)
    constraints: tuple[str, ...] = Field(default=(), max_length=20)
    assumptions: tuple[str, ...] = Field(default=(), max_length=20)
    required_capabilities: tuple[str, ...] = Field(default=(), max_length=16)
    risk_flags: tuple[str, ...] = Field(default=(), max_length=20)
    ambiguities: tuple[str, ...] = Field(default=(), max_length=20)
    next_action: IntentAction


class AdjudicatedIntent(SchemaV1):
    """Local decision after adjudicating a model intent against the envelope."""

    envelope_hash: str = Field(pattern=r'^[0-9a-f]{64}$')
    intent: IntentKind
    goal: str = Field(max_length=2000)
    target_ids: tuple[Identifier, ...] = ()
    reference_ids: tuple[Identifier, ...] = ()
    excluded_ids: tuple[Identifier, ...] = ()
    deliverables: tuple[str, ...] = Field(default=(), max_length=20)
    constraints: tuple[str, ...] = Field(default=(), max_length=20)
    assumptions: tuple[str, ...] = Field(default=(), max_length=20)
    capabilities: tuple[str, ...] = Field(default=(), max_length=16)
    dropped_capabilities: tuple[str, ...] = Field(default=(), max_length=16)
    scope_violations: tuple[str, ...] = Field(default=(), max_length=20)
    risk_flags: tuple[str, ...] = Field(default=(), max_length=20)
    clarification_questions: tuple[str, ...] = Field(default=(), max_length=10)
    next_action: IntentAction
