"""Persistence adapters for local report-review projects."""

from .issue_repository import IssueRepository
from .project_repository import ProjectRepository

__all__ = ["IssueRepository", "ProjectRepository"]
