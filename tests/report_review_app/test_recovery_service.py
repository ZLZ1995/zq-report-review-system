from __future__ import annotations

import json
from pathlib import Path

from asset_based_agent.report_review_app.domain.enums import RoundStatus
from asset_based_agent.report_review_app.domain.models import AuditRound
from asset_based_agent.report_review_app.repositories.project_repository import (
    ProjectRepository,
)
from asset_based_agent.report_review_app.services.recovery_service import RecoveryService


def test_network_paused_round_is_recoverable(tmp_path: Path) -> None:
    repository = ProjectRepository(tmp_path / "projects")
    project = repository.create("project")
    round_dir = Path(project.project_path) / "rounds" / "round-001"
    round_dir.mkdir(parents=True)
    progress = round_dir / "progress.json"
    error = round_dir / "error_snapshot.json"
    progress.write_text(
        json.dumps({"stage": "running_llm_review", "percent": 60}),
        encoding="utf-8",
    )
    error.write_text(
        json.dumps({"message": "network unavailable"}),
        encoding="utf-8",
    )
    project.rounds.append(
        AuditRound(
            round_id="ROUND-1",
            round_number=1,
            status=RoundStatus.PAUSED_NETWORK_ERROR,
            progress_path=str(progress),
            issues_path=str(round_dir / "issues.json"),
            error_snapshot_path=str(error),
        )
    )

    states = RecoveryService().inspect(project)

    assert states[0].recoverable is True
    assert states[0].percent == 60
    assert states[0].error_message == "network unavailable"
