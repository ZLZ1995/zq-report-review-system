"""Context manifest: every model call is explainable, reproducible, trimmable.

The manifest records hashes and identifiers only — never prompt text, prices
or secrets. Pinned sections (business red lines, the turn scope and selected
skill contracts) are never trimmed. The user-facing diagnostics view lists
which source kinds were used without exposing internals.
"""
from __future__ import annotations

import json
from hashlib import sha256
from typing import Literal

from pydantic import Field, field_validator

from ..agent_contracts import Identifier, Record
from .context_budget import estimate_tokens, plan_budget
from .evidence_retriever import EvidenceFragment, retrieve_evidence
from .turn_context import TurnEnvelope, envelope_hash

MEMORY_LIMIT = 5
_REDLINE_TOKENS = 400
_SCOPE_TOKENS = 300
_SKILL_CONTRACT_TOKENS = 200
_SUMMARY_TOKENS = 200
_RECEIPT_TOKENS = 50


class ContextManifest(Record):
    schema_version: Literal[1] = 1
    manifest_id: str = Field(pattern=r'^[0-9a-f]{64}$')
    envelope_hash: str = Field(pattern=r'^[0-9a-f]{64}$')
    system_policy_hash: str = Field(pattern=r'^[0-9a-f]{64}$')
    skill_pins: tuple[tuple[str, str, str], ...] = ()
    memory_ids: tuple[Identifier, ...] = Field(default=(), max_length=MEMORY_LIMIT)
    summary_ids: tuple[Identifier, ...] = ()
    summaries_non_original: bool = False
    evidence_fragment_ids: tuple[Identifier, ...] = ()
    tool_receipt_ids: tuple[Identifier, ...] = ()
    budgets: dict[str, int]

    @field_validator('schema_version', mode='before')
    @classmethod
    def integer_version(cls, value):
        if type(value) is not int:
            raise ValueError('Invalid schema version')
        return value


def build_manifest(*, envelope, system_policy_hash, skills=(), memories=(),
                   summaries=(), evidence=(), tool_receipt_ids=(),
                   total_budget) -> ContextManifest:
    envelope = TurnEnvelope.model_validate(envelope.model_dump())
    if not isinstance(system_policy_hash, str) or len(system_policy_hash) != 64:
        raise ValueError('系统策略哈希无效')
    if type(total_budget) is not int or total_budget <= 0:
        raise ValueError('总预算必须是正整数')

    fragments = [EvidenceFragment.model_validate(
        item.model_dump() if isinstance(item, EvidenceFragment) else item)
        for item in evidence]
    for item in fragments:
        if item.sheet_visibility != 'visible':
            raise ValueError('隐藏表内容不得进入模型上下文')
    selected_ids = {item.id for item in envelope.selected_attachment_versions}
    for item in fragments:
        if item.file_id not in selected_ids:
            raise ValueError('证据片段不属于本轮选定的资料范围')

    skills = sorted(
        ({'id': s['id'], 'version': s['version'], 'rules_sha256': s['rules_sha256']}
         for s in skills),
        key=lambda item: item['id'])
    memories = list(memories)[:MEMORY_LIMIT]
    summaries = list(summaries)
    receipts = tuple(tool_receipt_ids)

    desired = {
        'redlines': {'tokens': _REDLINE_TOKENS, 'pinned': True},
        'scope': {'tokens': _SCOPE_TOKENS, 'pinned': True},
        'skill_contracts': {'tokens': _SKILL_CONTRACT_TOKENS * len(skills), 'pinned': True},
        'evidence': {'tokens': sum(estimate_tokens(f.text) for f in fragments),
                     'pinned': False},
        'memories': {'tokens': sum(estimate_tokens(m['text']) for m in memories),
                     'pinned': False},
        'history': {'tokens': _SUMMARY_TOKENS * len(summaries), 'pinned': False},
        'receipts': {'tokens': _RECEIPT_TOKENS * len(receipts), 'pinned': False},
    }
    budgets = plan_budget(desired, total_budget)

    retrieval = retrieve_evidence(fragments, budget=budgets['evidence'])
    kept_memories, used = [], 0
    for memory in memories:
        cost = estimate_tokens(memory['text'])
        if used + cost > budgets['memories']:
            continue
        kept_memories.append(memory)
        used += cost

    payload = {
        'schema_version': 1,
        'envelope_hash': envelope_hash(envelope),
        'system_policy_hash': system_policy_hash,
        'skill_pins': tuple((s['id'], s['version'], s['rules_sha256']) for s in skills),
        'memory_ids': tuple(m['id'] for m in kept_memories),
        'summary_ids': tuple(s['id'] for s in summaries),
        'summaries_non_original': bool(summaries),
        'evidence_fragment_ids': tuple(f.id for f in retrieval.fragments),
        'tool_receipt_ids': receipts,
        'budgets': budgets,
    }
    manifest_id = sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False,
                                    allow_nan=False).encode('utf-8')).hexdigest()
    return ContextManifest(manifest_id=manifest_id, **payload)


def diagnostics_view(manifest: ContextManifest) -> dict:
    """User-facing source summary; no prompts, prices, budgets or secrets."""
    manifest = ContextManifest.model_validate(manifest.model_dump())
    return {
        'sources': {
            'evidence_fragments': len(manifest.evidence_fragment_ids),
            'memories': len(manifest.memory_ids),
            'summaries': len(manifest.summary_ids),
            'skills': [pin[0] for pin in manifest.skill_pins],
            'tool_receipts': len(manifest.tool_receipt_ids),
        },
        'summaries_are_leads_not_evidence': manifest.summaries_non_original,
    }
