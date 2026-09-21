"""Application-facing project operations."""

from __future__ import annotations

from ..domain.enums import ProjectStatus
from ..domain.models import AuditProject
from ..repositories.project_repository import ProjectRepository


class ProjectDeletionError(RuntimeError):
    pass


class ProjectService:
    def __init__(self, repository: ProjectRepository) -> None:
        self.repository = repository

    def create_project(self, name: str) -> AuditProject:
        return self.repository.create(name)

    def continue_project(self, project_id: str) -> AuditProject:
        return self.repository.get(project_id)

    def list_projects(self) -> list[AuditProject]:
        return self.repository.list()

    def delete_project(self, project_id: str) -> None:
        project = self.repository.get(project_id)
        if project.status == ProjectStatus.AUDITING:
            raise ProjectDeletionError("项目正在审核中，暂时不能删除。")
        self.repository.delete(project_id)
