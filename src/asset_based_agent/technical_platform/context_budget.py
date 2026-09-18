"""Token-aware context budgeting; pinned sections are never trimmed.

Estimation is a deterministic local heuristic (no tokenizer dependency):
CJK characters cost one unit each, other characters a quarter unit, so
Chinese-dominant business text budgets conservatively.
"""
from __future__ import annotations

import math
import re

SECTIONS = ('redlines', 'scope', 'skill_contracts', 'evidence',
            'memories', 'history', 'receipts')

_CJK = re.compile(r'[㐀-鿿豈-﫿]')


def estimate_tokens(text: str) -> int:
    if not isinstance(text, str):
        raise ValueError('预算估算只接受文本')  # noqa: TRY004 - user-facing boundary
    cjk = len(_CJK.findall(text))
    other = len(text) - cjk
    return math.ceil(cjk + other / 4)


def plan_budget(sections: dict, total: int) -> dict[str, int]:
    """Allocate `total` across known sections; pinned sections always get full."""
    if type(total) is not int or total < 0:
        raise ValueError('总预算必须是非负整数')
    unknown = set(sections) - set(SECTIONS)
    if unknown:
        raise ValueError('未知的上下文分区：' + '、'.join(sorted(unknown)))
    plan = {name: 0 for name in SECTIONS}
    pinned_total = 0
    unpinned = {}
    for name, spec in sections.items():
        tokens, pinned = spec['tokens'], bool(spec['pinned'])
        if type(tokens) is not int or tokens < 0:
            raise ValueError('分区预算必须是非负整数')
        if pinned:
            plan[name] = tokens
            pinned_total += tokens
        else:
            unpinned[name] = tokens
    remaining = max(0, total - pinned_total)
    desired = sum(unpinned.values())
    if not unpinned or desired == 0:
        return plan
    if desired <= remaining:
        plan.update(unpinned)
        return plan
    allocated = 0
    shares = {}
    for name in SECTIONS:
        if name not in unpinned:
            continue
        share = remaining * unpinned[name] // desired
        shares[name] = share
        allocated += share
    leftover = remaining - allocated
    for name in SECTIONS:
        if leftover <= 0:
            break
        if name in shares:
            shares[name] += 1
            leftover -= 1
    plan.update(shares)
    return plan


def trim_to_budget(items, budget: int):
    """Keep items in order while the cumulative estimate fits the budget."""
    if type(budget) is not int or budget < 0:
        raise ValueError('预算必须是非负整数')
    kept, used = [], 0
    for identity, text in items:
        cost = estimate_tokens(text)
        if used + cost > budget:
            continue
        kept.append((identity, text))
        used += cost
    return kept
