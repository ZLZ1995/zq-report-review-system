"""Write-side governance for memory: dedupe, conflict, sensitive scan.

Nothing is written silently: sensitive candidates are always rejected,
duplicates are skipped, conflicts keep the existing record unless the user
explicitly confirms a supersede, and project facts wait for confirmation.
"""
from __future__ import annotations

from ..agent_contracts import Identifier, Record
from .memory_candidates import MemoryCandidate, validate_transition
from .turn_normalizer import normalize_text

_LIVE_STATES = ('proposed', 'confirmed', 'active')


class ConflictRecord(Record):
    candidate_id: Identifier
    existing_id: Identifier
    existing_text: str


class RejectedCandidate(Record):
    candidate_id: Identifier
    reason: str


class WritePlan(Record):
    writable: tuple[MemoryCandidate, ...] = ()
    duplicates: tuple[MemoryCandidate, ...] = ()
    conflicts: tuple[ConflictRecord, ...] = ()
    rejected: tuple[RejectedCandidate, ...] = ()
    pending_confirmation: tuple[MemoryCandidate, ...] = ()
    superseded_ids: tuple[Identifier, ...] = ()


def prepare_writes(candidates, existing_records, *, confirmed_ids=(),
                   supersede_conflicts=False, now) -> WritePlan:
    """Decide what may be persisted; the plan is data, the caller persists."""
    confirmed = set(confirmed_ids)
    live = [item for item in existing_records if item.get('status') in _LIVE_STATES]
    writable, duplicates, conflicts, rejected, pending, superseded = [], [], [], [], [], []
    for candidate in candidates:
        candidate = MemoryCandidate.model_validate(
            candidate.model_dump() if isinstance(candidate, MemoryCandidate) else candidate)
        if candidate.sensitivity == 'sensitive':
            rejected.append(RejectedCandidate(candidate_id=candidate.id,
                                              reason='sensitive'))
            continue
        match = next((item for item in live if item.get('key') == candidate.key), None)
        if match is not None and normalize_text(match.get('text', '')) == normalize_text(candidate.text):
            duplicates.append(candidate)
            continue
        if match is not None:
            if supersede_conflicts and candidate.id in confirmed:
                writable.append(candidate)
                superseded.append(match['id'])
            else:
                conflicts.append(ConflictRecord(candidate_id=candidate.id,
                                                existing_id=match['id'],
                                                existing_text=match.get('text', '')))
            continue
        if candidate.id in confirmed:
            writable.append(candidate)
        else:
            pending.append(candidate)
    return WritePlan(writable=tuple(writable), duplicates=tuple(duplicates),
                     conflicts=tuple(conflicts), rejected=tuple(rejected),
                     pending_confirmation=tuple(pending),
                     superseded_ids=tuple(superseded))


def apply_revocation(records, identity, *, now):
    """Return records with the target revoked; invalid transitions raise."""
    result = []
    for item in records:
        item = dict(item)
        if item['id'] == identity:
            if not validate_transition(item['status'], 'revoked'):
                raise ValueError('当前状态不允许撤销')
            item['status'] = 'revoked'
            item['revoked_at'] = now.isoformat() if hasattr(now, 'isoformat') else now
        result.append(item)
    return result


def mark_project_memories_deleted(records):
    """Delete-project flow: only project-scoped memories are removed."""
    return [item for item in records if item.get('scope') != 'project']


def ignore_for_turn(identity) -> str:
    """Produce an ignore token for this turn; the record itself is untouched."""
    if not identity:
        raise ValueError('忽略目标不能为空')
    return identity
