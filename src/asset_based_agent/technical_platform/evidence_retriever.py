"""Evidence retrieval: target-first ordering, hard hidden-sheet filter.

Excel hidden/veryHidden worksheet content is a permanent business red line:
fragments carrying hidden sheet visibility never enter any manifest or model
context; they are reported as dropped so the user can see the protection.
"""
from __future__ import annotations

from typing import Literal

from pydantic import Field

from ..agent_contracts import Identifier, Record
from .context_budget import estimate_tokens


class EvidenceFragment(Record):
    id: Identifier
    file_id: Identifier
    file_name: str = Field(min_length=1, max_length=255)
    role: Literal['target', 'reference']
    sheet_visibility: Literal['visible', 'hidden', 'veryHidden'] = 'visible'
    text: str = Field(min_length=1, max_length=20000)


class RetrievalResult(Record):
    fragments: tuple[EvidenceFragment, ...] = ()
    dropped_hidden: tuple[Identifier, ...] = ()
    dropped_budget: tuple[Identifier, ...] = ()


def retrieve_evidence(fragments, *, budget: int) -> RetrievalResult:
    """Order target evidence before reference; hidden sheets never pass."""
    if type(budget) is not int or budget < 0:
        raise ValueError('证据预算必须是非负整数')
    parsed = [EvidenceFragment.model_validate(
        item.model_dump() if isinstance(item, EvidenceFragment) else item)
        for item in fragments]
    hidden = tuple(item.id for item in parsed if item.sheet_visibility != 'visible')
    visible = [item for item in parsed if item.sheet_visibility == 'visible']
    ordered = ([item for item in visible if item.role == 'target']
               + [item for item in visible if item.role == 'reference'])
    kept, dropped, used = [], [], 0
    for item in ordered:
        cost = estimate_tokens(item.text)
        if used + cost > budget:
            dropped.append(item.id)
            continue
        kept.append(item)
        used += cost
    return RetrievalResult(fragments=tuple(kept), dropped_hidden=hidden,
                           dropped_budget=tuple(dropped))
