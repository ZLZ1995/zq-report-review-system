import hashlib
import json
import os
import zipfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox

from asset_based_agent.technical_platform.skill_manager import SkillManagerDialog
from asset_based_agent.technical_platform.store import PlatformStore


def test_install_cancel_confirm_and_version_controls(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    assert app is not None
    path = tmp_path / "skill.zip"
    manifest = {"schema_version": 1, "id": "test.external", "version": "1.0.0",
                "name": "External", "adapter": "report.review",
                "capabilities": ["read_selected_files"], "dependencies": {},
                "files": {"SKILL.md": hashlib.sha256(b"rules").hexdigest()}}
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("manifest.json", json.dumps(manifest))
        archive.writestr("SKILL.md", "rules")
    dialog = SkillManagerDialog(PlatformStore(tmp_path / "db.sqlite", "alice"))
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a, **k: (str(path), ""))
    monkeypatch.setattr(dialog, "confirm", lambda text: False)
    dialog.install_package()
    assert dialog.versions.count() == 0
    monkeypatch.setattr(dialog, "confirm", lambda text: True)
    dialog.install_package()
    assert dialog.versions.count() == 1
    assert not dialog.manager.list_versions()[0]["enabled"]
    dialog.versions.setCurrentRow(0)
    assert "受支持的适配器" in dialog.details.toPlainText()
    assert "尚未接入任务执行" not in dialog.details.toPlainText()
    dialog.activate_selected()
    assert dialog.manager.list_versions()[0]["enabled"]
    dialog.disable_selected()
    assert not dialog.manager.list_versions()[0]["enabled"]
    dialog.close()


def test_confirmation_defaults_to_no_and_plain_text(tmp_path, monkeypatch):
    from PySide6.QtCore import Qt

    app = QApplication.instance() or QApplication([])
    assert app is not None
    dialog = SkillManagerDialog(PlatformStore(tmp_path / "db.sqlite", "alice"))
    def inspect(box):
        assert box.defaultButton() == box.button(QMessageBox.StandardButton.No)
        assert box.textFormat() == Qt.TextFormat.PlainText
        return QMessageBox.StandardButton.No
    monkeypatch.setattr(QMessageBox, "exec", inspect)
    assert not dialog.confirm("<b>package</b>")
    dialog.close()
