"""User feedback capture. Feedback never changes a rule or memory directly."""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import ClassVar
from uuid import uuid4

from .store import now


@dataclass(frozen=True)
class FeedbackReceipt:
    id: str
    proposal_id: str | None


class FeedbackService:
    KINDS: ClassVar = {
        "ignored_issue", "false_positive", "missed_issue", "bad_advice", "preference"
    }

    def __init__(self, store):
        self.store = store

    def record(self, *, run_id, kind, summary, evidence_refs):
        run = self.store.run(run_id)
        if kind not in self.KINDS:
            raise ValueError("Invalid feedback kind")
        summary = summary.strip()
        if not summary or len(summary) > 1000:
            raise ValueError("Invalid feedback summary")
        if (not isinstance(evidence_refs, list) or len(evidence_refs) > 50
                or any(not isinstance(item, str) or not item.strip() or len(item) > 128
                       for item in evidence_refs)):
            raise ValueError("Invalid feedback evidence")
        if kind != "ignored_issue" and not evidence_refs:
            raise ValueError("Improvement feedback requires evidence")
        feedback_id = uuid4().hex
        proposal_id = None if kind == "ignored_issue" else uuid4().hex
        snapshot = json.loads(run["snapshot"])
        skill_id = snapshot.get("skill_id") or snapshot.get("skill") or "report.review"
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute(
                "INSERT INTO feedback_records VALUES(?,?,?,?,?,?,?)",
                (feedback_id, self.store.owner, run_id, kind, summary,
                 json.dumps(evidence_refs, ensure_ascii=False), now()),
            )
            if proposal_id:
                db.execute(
                    "INSERT INTO skill_improvement_proposals "
                    "(id,owner,feedback_id,skill_id,status,summary,evidence_json,test_ids_json,created,updated) "
                    "VALUES(?,?,?,?, 'candidate', ?, ?, '[]', ?, ?)",
                    (proposal_id, self.store.owner, feedback_id, skill_id, summary,
                     json.dumps(evidence_refs, ensure_ascii=False), now(), now()),
                )
        return FeedbackReceipt(feedback_id, proposal_id)
