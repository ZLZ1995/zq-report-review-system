"""Unknown-state reconciliation: check first, never blind-replay.

Model calls reconcile by client_job_id against the remote ledger; a missing
record goes to manual review instead of re-sending a billable request.
Office writes and browser actions in unknown state are never replayed
automatically.
"""
from __future__ import annotations

from typing import Literal

from ..agent_contracts import Identifier, Record

_Reconciled = Literal['settled_charged', 'settled_unpaid', 'manual_review']


class ReconciliationDecision(Record):
    subject_id: Identifier
    outcome: _Reconciled
    detail: str


def reconcile_unknown(kind: str, subject_id: str, *, remote_lookup) -> ReconciliationDecision:
    if kind == 'model_call':
        status = remote_lookup(subject_id)
        if status is None:
            return ReconciliationDecision(
                subject_id=subject_id, outcome='manual_review',
                detail='远程无此任务记录，先人工对账，不重发可能扣费的请求')
        if status in ('charged', 'completed', 'success'):
            return ReconciliationDecision(
                subject_id=subject_id, outcome='settled_charged',
                detail='远程账目确认已计费，按既有结果对账')
        return ReconciliationDecision(
            subject_id=subject_id, outcome='settled_unpaid',
            detail='远程账目确认未计费，可安全安排后续处理')
    return ReconciliationDecision(
        subject_id=subject_id, outcome='manual_review',
        detail='Office/浏览器/交付类写动作状态未知，不得自动重放，转人工核对')
