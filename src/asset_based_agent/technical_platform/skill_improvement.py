"""Review candidate Skill improvements without publishing or activating them."""

from __future__ import annotations

import json
from dataclasses import dataclass

from .store import now


@dataclass(frozen=True)
class SkillImprovementProposal:
    id: str
    skill_id: str
    status: str
    feedback_kind: str
    summary: str
    evidence_refs: tuple[str, ...]
    test_ids: tuple[str, ...]


class SkillImprovementService:
    def __init__(self, store):
        self.store = store

    def get(self, identity):
        with self.store.connect() as db:
            row = db.execute(
                "SELECT p.*,f.kind AS feedback_kind FROM skill_improvement_proposals p "
                "JOIN feedback_records f ON f.id=p.feedback_id WHERE p.id=? AND p.owner=?",
                (identity, self.store.owner),
            ).fetchone()
        if row is None:
            raise PermissionError(
                "Improvement proposal does not exist or is not accessible"
            )
        return SkillImprovementProposal(
            id=row["id"],
            skill_id=row["skill_id"],
            status=row["status"],
            feedback_kind=row["feedback_kind"],
            summary=row["summary"],
            evidence_refs=tuple(json.loads(row["evidence_json"])),
            test_ids=tuple(json.loads(row["test_ids_json"])),
        )

    def validate(self, identity, *, test_ids, tests_passed):
        proposal = self.get(identity)
        if (
            not isinstance(test_ids, list)
            or not test_ids
            or any(
                not isinstance(item, str) or not item.strip() or len(item) > 200
                for item in test_ids
            )
        ):
            raise ValueError("Validation requires named tests")
        if tests_passed is not True:
            raise ValueError("All proposal tests must pass")
        if proposal.status not in {"candidate", "validated"}:
            raise ValueError("Proposal cannot be validated from its current state")
        encoded = json.dumps(test_ids, ensure_ascii=False)
        with self.store.connect() as db:
            db.execute(
                "UPDATE skill_improvement_proposals SET status='validated',test_ids_json=?,"
                "updated=? WHERE id=? AND owner=?",
                (encoded, now(), identity, self.store.owner),
            )
        return self.get(identity)
