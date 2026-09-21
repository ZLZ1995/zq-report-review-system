"""Deterministic clarification matching for waiting_user material resolution.

No model calls here: a user reply either names exactly one candidate for every
ambiguous role (by entity, period wording, or file name) or we ask again.
"""
from __future__ import annotations


def _period_forms(period_end):
    if not period_end:
        return ()
    try:
        year, month, _day = period_end.split('-')
    except ValueError:
        return ()
    m = str(int(month))
    return (period_end, f'{year}年{m}月', f'{year}年{month}月',
            f'{year}.{m}', f'{year}/{m}', f'{year}-{month}', f'{year}年')


def _mentions(candidate, file_name, text):
    entity = candidate.get('entity_name')
    if entity and entity in text:
        return True
    if any(form in text for form in _period_forms(candidate.get('period_end'))):
        return True
    if file_name:
        stem = file_name.rsplit('.', 1)[0]
        if file_name in text or (stem and stem in text):
            return True
    return False


def match_clarification(pending, files, user_text):
    """Map a free-text clarification to a role override, or None if unclear.

    Conservative contract: every role with multiple candidates must match
    exactly one candidate; zero or multiple matches return None so the caller
    asks again instead of guessing.  Single-candidate roles keep their
    persisted selection.
    """
    if not isinstance(pending, dict):
        return None
    text = (user_text or '').strip()
    if not text:
        return None
    candidates = pending.get('candidates') or {}
    selected = dict(pending.get('selected') or {})
    names = {item['id']: item.get('name', item['id']) for item in files}
    for role, members in candidates.items():
        if len(members) <= 1:
            continue
        matched = [c for c in members
                   if _mentions(c, names.get(c.get('artifact_id'), ''), text)]
        if len(matched) != 1:
            return None
        selected[role] = matched[0]['artifact_id']
    return selected or None
