"""Runtime path configuration for the local desktop application."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class RuntimePaths:
    app_data: Path
    user_config: Path
    projects_root: Path
    client_instance: Path


@dataclass(frozen=True)
class RemoteClientSettings:
    enabled: bool
    server_url: str


def load_runtime_paths() -> RuntimePaths:
    app_data_root = Path(
        os.environ.get("APPDATA") or (Path.home() / "AppData" / "Roaming")
    )
    app_data = app_data_root / "AIExcelAgent" / "report-review"
    documents = Path(os.environ.get("USERPROFILE") or Path.home()) / "Documents"
    projects_root = Path(
        os.environ.get("AI_EXCEL_AGENT_REVIEW_PROJECTS")
        or (documents / "AIExcelAgent" / "ReportReviewProjects")
    )
    return RuntimePaths(
        app_data=app_data,
        user_config=app_data / "users.json",
        projects_root=projects_root,
        client_instance=app_data / "client-instance.json",
    )


def load_remote_client_settings() -> RemoteClientSettings:
    enabled = os.environ.get("ZQ_REPORT_REVIEW_REMOTE_AUTH", "").strip().lower() in {
        "1",
        "true",
        "yes",
    }
    server_url = os.environ.get("ZQ_REPORT_REVIEW_SERVER_URL", "").strip().rstrip("/")
    if enabled and not server_url:
        raise ValueError("ZQ_REPORT_REVIEW_SERVER_URL is required in remote mode")
    if server_url and not server_url.startswith("https://"):
        raise ValueError("ZQ_REPORT_REVIEW_SERVER_URL must use HTTPS")
    return RemoteClientSettings(enabled=enabled, server_url=server_url)
