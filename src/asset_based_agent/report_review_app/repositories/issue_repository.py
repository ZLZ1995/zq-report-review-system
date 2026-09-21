"""Persistence for round-scoped structured issues and advice."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from ..domain.models import ReviewIssue


class IssueRepository:
    def load_issues(self, path: Path) -> list[ReviewIssue]:
        if not path.is_file():
            raise FileNotFoundError(f"issues file not found: {path}")
        payload = json.loads(path.read_text(encoding="utf-8"))
        return [ReviewIssue.model_validate(item) for item in payload.get("issues", [])]

    def save_issues(
        self,
        path: Path,
        *,
        project_id: str,
        round_number: int,
        issues: list[ReviewIssue],
        status: str = "completed",
    ) -> Path:
        return self._write_json(
            path,
            {
                "schema_version": "1.0",
                "project_id": project_id,
                "round_number": round_number,
                "status": status,
                "issues": [item.model_dump(mode="json") for item in issues],
            },
        )

    def load_advice(self, path: Path) -> dict[str, Any]:
        if not path.is_file():
            return {"schema_version": "1.0", "items": {}}
        return json.loads(path.read_text(encoding="utf-8"))

    def save_advice(self, path: Path, payload: dict[str, Any]) -> Path:
        return self._write_json(path, payload)

    def load_conversations(self, path: Path) -> dict[str, Any]:
        if not path.is_file():
            return {"schema_version": "1.0", "items": {}}
        return json.loads(path.read_text(encoding="utf-8"))

    def save_conversations(self, path: Path, payload: dict[str, Any]) -> Path:
        return self._write_json(path, payload)

    @staticmethod
    def _write_json(path: Path, payload: dict[str, Any]) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        os.replace(temporary, path)
        return path
