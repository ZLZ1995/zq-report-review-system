"""File-system repository for portable local review projects."""

from __future__ import annotations

import json
import os
import shutil
import uuid
from pathlib import Path

from ..domain.models import AuditProject, utc_now


class ProjectRepository:
    """Store each project as an independent, portable directory."""

    MANIFEST_NAME = "project.json"

    def __init__(self, projects_root: Path) -> None:
        self.projects_root = projects_root.resolve()
        self.projects_root.mkdir(parents=True, exist_ok=True)

    def create(self, name: str) -> AuditProject:
        cleaned_name = name.strip()
        if not cleaned_name:
            raise ValueError("project name is required")
        project_id = str(uuid.uuid4())
        project_dir = self.projects_root / project_id
        self._create_layout(project_dir)
        project = AuditProject(
            project_id=project_id,
            name=cleaned_name,
            project_path=str(project_dir),
        )
        self.save(project)
        return project

    def save(self, project: AuditProject) -> Path:
        project_dir = self._resolve_project_dir(project.project_path)
        self._create_layout(project_dir)
        project.updated_at = utc_now()
        manifest = project_dir / self.MANIFEST_NAME
        self._write_json_atomic(manifest, project.model_dump(mode="json"))
        return manifest

    def get(self, project_id: str) -> AuditProject:
        manifest = self.projects_root / project_id / self.MANIFEST_NAME
        if not manifest.is_file():
            raise FileNotFoundError(f"project not found: {project_id}")
        return AuditProject.model_validate_json(manifest.read_text(encoding="utf-8"))

    def list(self) -> list[AuditProject]:
        projects: list[AuditProject] = []
        for manifest in self.projects_root.glob(f"*/{self.MANIFEST_NAME}"):
            try:
                projects.append(
                    AuditProject.model_validate_json(manifest.read_text(encoding="utf-8"))
                )
            except (OSError, ValueError):
                continue
        return sorted(projects, key=lambda item: item.updated_at, reverse=True)

    def delete(self, project_id: str) -> None:
        project_dir = self._resolve_project_id(project_id)
        manifest = project_dir / self.MANIFEST_NAME
        if not manifest.is_file():
            raise FileNotFoundError(f"project not found: {project_id}")
        shutil.rmtree(project_dir)

    def _resolve_project_id(self, project_id: str) -> Path:
        if (
            not project_id
            or Path(project_id).name != project_id
            or "/" in project_id
            or "\\" in project_id
        ):
            raise ValueError("invalid project id")
        project_dir = (self.projects_root / project_id).resolve()
        try:
            project_dir.relative_to(self.projects_root)
        except ValueError as exc:
            raise ValueError("invalid project id") from exc
        if project_dir == self.projects_root:
            raise ValueError("invalid project id")
        return project_dir

    def _resolve_project_dir(self, raw_path: str) -> Path:
        project_dir = Path(raw_path).resolve()
        try:
            project_dir.relative_to(self.projects_root)
        except ValueError as exc:
            raise ValueError("project path escapes configured projects root") from exc
        return project_dir

    @staticmethod
    def _create_layout(project_dir: Path) -> None:
        for relative in ("files", "rounds", "final"):
            (project_dir / relative).mkdir(parents=True, exist_ok=True)
        events = project_dir / "audit_events.jsonl"
        events.touch(exist_ok=True)

    @staticmethod
    def _write_json_atomic(path: Path, payload: dict[str, object]) -> None:
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        os.replace(temporary, path)
