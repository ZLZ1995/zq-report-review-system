"""Inspect interrupted rounds and expose safe recovery decisions."""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from ..domain.enums import RoundStatus
from ..domain.models import AuditProject

RECOVERABLE_STATUSES = {
    RoundStatus.PAUSED_NETWORK_ERROR,
    RoundStatus.PAUSED_USER_CANCELLED,
    RoundStatus.FAILED_SCHEMA,
    RoundStatus.FAILED_INTERNAL,
}


class RecoveryState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    round_number: int
    status: RoundStatus
    recoverable: bool
    stage: str
    percent: int
    error_message: str = ""


class RecoveryService:
    def inspect(self, project: AuditProject) -> list[RecoveryState]:
        states: list[RecoveryState] = []
        for audit_round in sorted(project.rounds, key=lambda item: item.round_number):
            if audit_round.status == RoundStatus.COMPLETED:
                continue
            progress = _safe_json(Path(audit_round.progress_path))
            error = _safe_json(Path(audit_round.error_snapshot_path))
            states.append(
                RecoveryState(
                    round_number=audit_round.round_number,
                    status=audit_round.status,
                    recoverable=audit_round.status in RECOVERABLE_STATUSES,
                    stage=str(progress.get("stage") or audit_round.status.value),
                    percent=_as_int(progress.get("percent")),
                    error_message=str(error.get("message") or ""),
                )
            )
        return states


def _safe_json(path: Path) -> dict[str, object]:
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _as_int(value: object) -> int:
    try:
        return int(str(value or 0))
    except ValueError:
        return 0
