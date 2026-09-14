import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from asset_based_agent.technical_platform.app import PlatformWindow
from asset_based_agent.technical_platform.project_catalog import ProjectCatalog


def test_reopen_restores_selected_session_and_missing_project_is_nonblocking(tmp_path, monkeypatch):
    monkeypatch.setenv("SystemDrive", "Z:")
    app = QApplication.instance() or QApplication([])
    assert app
    root = tmp_path / "project"
    root.mkdir()
    catalog = ProjectCatalog(tmp_path / "settings.sqlite", "alice")
    project = catalog.create_project("project", root)
    first = catalog.create_session(project, "first")
    catalog.create_session(project, "second")
    catalog.remember_session(first)
    window = PlatformWindow(ProjectCatalog(catalog.index_path, "alice"))
    assert window.project_id == project
    assert window.session_id == first
    window.close()
    root.rename(tmp_path / "moved")
    missing = PlatformWindow(ProjectCatalog(catalog.index_path, "alice"))
    assert missing.project_id is None
    assert "目录不可用" in missing.status.text()
    missing.close()
