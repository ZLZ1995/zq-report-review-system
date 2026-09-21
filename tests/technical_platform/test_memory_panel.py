def test_memory_editor_requires_explicit_confirmation():
    from PySide6.QtWidgets import QApplication, QDialog

    from asset_based_agent.technical_platform.ui.memory_panel import MemoryEditorDialog

    app = QApplication.instance() or QApplication([])
    dialog = MemoryEditorDialog(allow_session=True)
    dialog.key.setText("tone")
    dialog.text.setPlainText("Use concise wording")
    dialog._accept()
    assert dialog.result() == QDialog.DialogCode.Rejected
    assert "确认" in dialog.error.text()
    dialog.confirm.setChecked(True)
    dialog._accept()
    assert dialog.result() == QDialog.DialogCode.Accepted
    assert dialog.value() == {"scope": "project", "key": "tone", "text": "Use concise wording"}
    dialog.deleteLater()
    app.processEvents()


def test_memory_label_shows_scope_source_status_and_version(tmp_path):
    from asset_based_agent.technical_platform.memory_service import MemoryService
    from asset_based_agent.technical_platform.store import PlatformStore
    from asset_based_agent.technical_platform.ui.memory_panel import memory_label

    store = PlatformStore(tmp_path / "state.sqlite", "alice")
    project = store.create_project("one")
    identity = MemoryService(store).create(scope="project", project_id=project, key="tone",
                                           text="Concise", confirmed=True)
    label = memory_label(MemoryService(store).get(identity))
    assert "项目" in label and "用户明确确认" in label and "版本 1" in label
