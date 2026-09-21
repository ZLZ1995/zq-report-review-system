"""Audited Skill version governance; no prompt or customer text is accepted."""

from __future__ import annotations

import json
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import SkillRelease, SkillReleaseAudit
from .auth_service import ServiceError


def _public(item: SkillRelease) -> dict[str, object]:
    return {
        "release_id": item.release_id,
        "skill_id": item.skill_id,
        "version": item.version,
        "package_sha256": item.package_sha256,
        "schema_version": item.schema_version,
        "adapter": item.adapter,
        "capabilities": json.loads(item.capabilities_json),
        "minimum_client_version": item.minimum_client_version,
        "status": item.status,
    }


class SkillReleaseService:
    def list_admin(self, db: Session):
        rows = db.scalars(
            select(SkillRelease).order_by(
                SkillRelease.skill_id, SkillRelease.created_at.desc()
            )
        ).all()
        return [_public(item) for item in rows]

    def list_stable(self, db: Session):
        rows = db.scalars(
            select(SkillRelease)
            .where(SkillRelease.status == "stable")
            .order_by(SkillRelease.skill_id)
        ).all()
        return [_public(item) for item in rows]

    def create(self, db: Session, *, admin_user_id: str, payload) -> dict[str, object]:
        exists = db.scalar(
            select(SkillRelease).where(
                SkillRelease.skill_id == payload.skill_id,
                SkillRelease.version == payload.version,
            )
        )
        if exists is not None:
            raise ServiceError("skill_release_exists", "Skill 版本已存在。", 409)
        item = SkillRelease(
            release_id=str(uuid.uuid4()),
            skill_id=payload.skill_id,
            version=payload.version,
            package_sha256=payload.package_sha256,
            schema_version=payload.schema_version,
            adapter=payload.adapter,
            capabilities_json=json.dumps(payload.capabilities, sort_keys=True),
            minimum_client_version=payload.minimum_client_version,
            evidence_sha256=payload.evidence_sha256,
            test_report_sha256=payload.test_report_sha256,
            status="draft",
            created_by=admin_user_id,
        )
        db.add(item)
        db.add(
            SkillReleaseAudit(
                release_id=item.release_id,
                admin_user_id=admin_user_id,
                action="create",
                to_status="draft",
            )
        )
        db.commit()
        db.refresh(item)
        return _public(item)

    def transition(
        self, db: Session, *, admin_user_id: str, release_id: str, status: str
    ) -> dict[str, object]:
        item = db.get(SkillRelease, release_id)
        if item is None:
            raise ServiceError("skill_release_not_found", "Skill 版本不存在。", 404)
        allowed = {
            "draft": {"approved", "withdrawn"},
            "approved": {"stable", "withdrawn"},
            "stable": {"withdrawn"},
            "withdrawn": {"approved"},
        }
        if status not in allowed.get(item.status, set()):
            raise ServiceError(
                "invalid_skill_release_transition", "Skill 发布状态转换无效。", 409
            )
        old = item.status
        if status == "stable":
            prior = db.scalar(
                select(SkillRelease).where(
                    SkillRelease.skill_id == item.skill_id,
                    SkillRelease.status == "stable",
                    SkillRelease.release_id != item.release_id,
                )
            )
            if prior is not None:
                prior.status = "withdrawn"
                db.add(
                    SkillReleaseAudit(
                        release_id=prior.release_id,
                        admin_user_id=admin_user_id,
                        action="auto_withdraw",
                        from_status="stable",
                        to_status="withdrawn",
                    )
                )
        item.status = status
        db.add(
            SkillReleaseAudit(
                release_id=item.release_id,
                admin_user_id=admin_user_id,
                action="transition",
                from_status=old,
                to_status=status,
            )
        )
        db.commit()
        db.refresh(item)
        return _public(item)
