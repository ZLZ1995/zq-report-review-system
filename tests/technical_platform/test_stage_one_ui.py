import os
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QMessageBox

from asset_based_agent.technical_platform import app as platform
from asset_based_agent.technical_platform.store import PlatformStore


def test_claim_cancel_keeps_legacy_owner_then_confirmation_preserves_session(tmp_path, monkeypatch):
    qt = QApplication.instance() or QApplication([])
    assert qt
    legacy = PlatformStore(tmp_path / "state.sqlite", "local-preview")
    project = legacy.create_project("旧项目")
    legacy.create_session(project)
    target = PlatformStore(legacy.path, "alice")
    window = platform.PlatformWindow(target, client=object())
    monkeypatch.setattr(platform.QInputDialog, "getItem", lambda *a, **kw: (a[3][0], True))
    try:
        monkeypatch.setattr(QMessageBox, "question", lambda *a, **kw: QMessageBox.StandardButton.No)
        window.claim_legacy_project()
        assert legacy.project(project)
        assert target.projects() == []
        monkeypatch.setattr(QMessageBox, "question", lambda *a, **kw: QMessageBox.StandardButton.Yes)
        window.claim_legacy_project()
        assert window.project_id == project
        assert len(target.sessions(project)) == 1
    finally:
        window.close()


def test_version_check_runs_in_worker_and_displays_compatibility(tmp_path, monkeypatch):
    qt = QApplication.instance() or QApplication([])
    window = platform.PlatformWindow(PlatformStore(tmp_path / "state.sqlite", "alice"))
    monkeypatch.setattr(platform, "inspect_server", lambda url: {
        "server_api_version": "0.1.0", "server_build": "未提供", "user_request_supported": False,
    })
    try:
        window.check_versions()
        deadline = time.monotonic() + 5
        while window.version_worker is not None and time.monotonic() < deadline:
            qt.processEvents()
            time.sleep(0.01)
        assert window.version_worker is None
        assert "不兼容" in window.version_label.text()
        assert "构建号未提供" in window.version_label.text()
    finally:
        window.close()
