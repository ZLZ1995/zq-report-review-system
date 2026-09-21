from __future__ import annotations

import json
from pathlib import Path

import pytest

from asset_based_agent.report_review_app.domain.enums import ProjectStatus
from asset_based_agent.report_review_app.repositories.project_repository import (
    ProjectRepository,
)
from asset_based_agent.report_review_app.services.project_service import (
    ProjectDeletionError,
    ProjectService,
)


def test_create_project_builds_portable_directory_layout(tmp_path: Path) -> None:
    repository = ProjectRepository(tmp_path / "项目")

    project = repository.create("评估报告审核项目")
    project_dir = Path(project.project_path)

    assert (project_dir / "project.json").is_file()
    assert (project_dir / "audit_events.jsonl").is_file()
    assert (project_dir / "files").is_dir()
    assert (project_dir / "rounds").is_dir()
    assert (project_dir / "final").is_dir()
    assert repository.get(project.project_id).name == "评估报告审核项目"


def test_project_manifest_is_utf8_json_and_listed(tmp_path: Path) -> None:
    repository = ProjectRepository(tmp_path)
    created = repository.create("中文项目")

    payload = json.loads(
        (Path(created.project_path) / "project.json").read_text(encoding="utf-8")
    )
    projects = repository.list()

    assert payload["name"] == "中文项目"
    assert [item.project_id for item in projects] == [created.project_id]


def test_blank_project_name_is_rejected(tmp_path: Path) -> None:
    repository = ProjectRepository(tmp_path)

    with pytest.raises(ValueError):
        repository.create("  ")


def test_save_rejects_project_path_outside_configured_root(tmp_path: Path) -> None:
    repository = ProjectRepository(tmp_path / "allowed")
    project = repository.create("safe")
    project.project_path = str(tmp_path / "outside")

    with pytest.raises(ValueError, match="escapes"):
        repository.save(project)


def test_delete_removes_only_selected_project_directory(tmp_path: Path) -> None:
    repository = ProjectRepository(tmp_path / "projects")
    selected = repository.create("待删除项目")
    retained = repository.create("保留项目")

    repository.delete(selected.project_id)

    assert not Path(selected.project_path).exists()
    assert repository.get(retained.project_id).name == "保留项目"
    with pytest.raises(FileNotFoundError):
        repository.get(selected.project_id)


def test_delete_rejects_project_id_path_traversal(tmp_path: Path) -> None:
    repository = ProjectRepository(tmp_path / "projects")
    outside = tmp_path / "outside"
    outside.mkdir()

    with pytest.raises(ValueError, match="invalid project id"):
        repository.delete("../outside")

    assert outside.is_dir()


def test_project_service_refuses_to_delete_auditing_project(tmp_path: Path) -> None:
    repository = ProjectRepository(tmp_path / "projects")
    project = repository.create("审核中项目")
    project.status = ProjectStatus.AUDITING
    repository.save(project)

    with pytest.raises(ProjectDeletionError, match="审核"):
        ProjectService(repository).delete_project(project.project_id)

    assert Path(project.project_path).is_dir()
