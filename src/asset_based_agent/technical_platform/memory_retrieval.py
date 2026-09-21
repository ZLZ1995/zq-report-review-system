"""Bounded task-time memory selection with explicit scope precedence."""

from __future__ import annotations

from datetime import datetime, timezone

from .memory_service import _record


def _utc_now():
    return datetime.now(timezone.utc)


def retrieve_memories(
    store, session_id, *, clock=_utc_now, limit=16, character_budget=2500
):
    session = store.session(session_id)
    project_id = session["project"]
    current = clock().astimezone(timezone.utc).isoformat()
    with store.connect() as db:
        rows = db.execute(
            "SELECT * FROM memory_records WHERE owner=? AND status='active' "
            "AND (valid_until IS NULL OR valid_until>?) AND ("
            "scope='user' OR (scope='project' AND project=?) OR "
            "(scope='session' AND project=? AND session=?))",
            (store.owner, current, project_id, project_id, session_id),
        ).fetchall()
    rank = {"user": 0, "project": 1, "session": 2}
    # One effective value per key.  More specific scope wins; within a scope,
    # priority and newest immutable version win deterministically.
    selected = {}
    for row in rows:
        record = _record(row)
        score = (rank[record.scope], record.priority, record.updated, record.id)
        prior = selected.get(record.key)
        if prior is None or score > prior[0]:
            selected[record.key] = (score, record)
    ordered = sorted(
        (item[1] for item in selected.values()),
        key=lambda item: (-rank[item.scope], -item.priority, item.key, item.id),
    )
    result, remaining = [], character_budget
    for record in ordered:
        if len(result) >= limit:
            break
        if len(record.text) > remaining:
            continue
        result.append(record)
        remaining -= len(record.text)
    return result
