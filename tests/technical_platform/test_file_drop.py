import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QMimeData, QPoint, QPointF, Qt, QUrl
from PySide6.QtGui import QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import QApplication

from asset_based_agent.technical_platform.app import PlatformWindow
from asset_based_agent.technical_platform.store import PlatformStore


def drop(target, paths):
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(p)) for p in paths])
    enter = QDragEnterEvent(QPoint(10, 10), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)
    QApplication.sendEvent(target, enter)
    event = QDropEvent(QPointF(10, 10), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)
    QApplication.sendEvent(target, event)
    return event.isAccepted()


def test_drop_from_chat_and_composer_keeps_versions_without_execution(tmp_path):
    app = QApplication.instance() or QApplication([])
    store = PlatformStore(tmp_path / "state.db", "test")
    project = store.create_project("拖放测试")
    session = store.create_session(project)
    window = PlatformWindow(store)
    window.reload_projects(project)
    window.show()
    app.processEvents()
    window.composer.setPlainText("尚未发送")
    source = tmp_path / "报告.docx"
    source.write_bytes(b"version one")
    try:
        assert drop(window.transcript.viewport(), [source])
        assert len(store.files(project)) == 1
        assert drop(window.composer.viewport(), [source])
        assert len(store.files(project)) == 1
        source.write_bytes(b"version two")
        assert drop(window.composer.viewport(), [source])
        assert len(store.files(project)) == 2
        assert window.composer.toPlainText() == "尚未发送"
        assert store.runs(session) == []
        assert source.read_bytes() == b"version two"
    finally:
        window.close()


def test_mixed_drop_and_project_busy_guards(tmp_path):
    app = QApplication.instance() or QApplication([])
    store = PlatformStore(tmp_path / "state.db", "test")
    window = PlatformWindow(store)
    window.show()
    app.processEvents()
    source = tmp_path / "a.pdf"
    source.write_bytes(b"test")
    bad = tmp_path / "bad.exe"
    bad.write_bytes(b"test")
    try:
        drop(window.transcript.viewport(), [source])
        project = store.create_project("项目")
        store.create_session(project)
        window.reload_projects(project)
        window.set_busy(True)
        drop(window.transcript.viewport(), [source])
        assert store.files(project) == []
        window.set_busy(False)
        drop(window.transcript.viewport(), [tmp_path, bad, source, tmp_path / "missing.pdf"])
        assert len(store.files(project)) == 1
        assert "文件夹" in window.status.text()
        assert "bad.exe" in window.status.text()
        assert "missing.pdf" in window.status.text()
    finally:
        window.close()


def checked_names(window):
    return {window.files.item(i).text().split('\n')[0]
            for i in range(window.files.count())
            if window.files.item(i).checkState() == Qt.CheckState.Checked}


def test_new_upload_excludes_previous_run_files_and_refresh_preserves_scope(tmp_path):
    app = QApplication.instance() or QApplication([])
    store = PlatformStore(tmp_path / 'state.db', 'test')
    project = store.create_project('范围测试')
    session = store.create_session(project)
    old = tmp_path / '旧银行流水.xlsx'
    old.write_bytes(b'old')
    from asset_based_agent.technical_platform.skills import digest
    store.add_file(project, old, digest(old))
    window = PlatformWindow(store)
    window.reload_projects(project)
    app.processEvents()
    try:
        assert checked_names(window) == set()
        current = tmp_path / '本轮报告.docx'
        current.write_bytes(b'new')
        window.import_files([current])
        assert checked_names(window) == {current.name}
        window.refresh_details()
        assert checked_names(window) == {current.name}
        window.files.item(1).setCheckState(Qt.CheckState.Unchecked)
        window.refresh_details()
        assert checked_names(window) == set()
        window.import_files([current])  # Reattaching a duplicate explicitly selects it.
        assert checked_names(window) == {current.name}
        detail = tmp_path / '本轮明细.xlsx'
        detail.write_bytes(b'detail')
        window.import_files([detail])  # Separate drops before submission accumulate.
        assert checked_names(window) == {current.name, detail.name}
        window._scope_submitted = True
        next_report = tmp_path / '下一轮报告.docx'
        next_report.write_bytes(b'next')
        window.import_files([next_report])
        assert checked_names(window) == {next_report.name}
        assert len(store.files(project)) == 4  # History is preserved, not deleted.
        window.new_session()
        assert window.session_id != session
        assert checked_names(window) == set()
    finally:
        window.close()


def test_review_scope_can_be_rejected_before_task_creation(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    app = QApplication.instance() or QApplication([])
    store = PlatformStore(tmp_path / 'state.db', 'test')
    project = store.create_project('送审确认')
    session = store.create_session(project)
    window = PlatformWindow(store)
    window.reload_projects(project)
    app.processEvents()
    source = tmp_path / '本轮报告.docx'
    source.write_bytes(b'new')
    window.import_files([source])
    window.client = object()
    window.network_state = 'connected'
    window.composer.setPlainText('只审核本轮报告')
    prompts = []

    def reject(parent, title, text, *args):
        prompts.append(text)
        return QMessageBox.StandardButton.Cancel

    monkeypatch.setattr(QMessageBox, 'question', reject)
    try:
        from asset_based_agent.technical_platform.skills import REVIEW
        window.execute_plan('只审核本轮报告', REVIEW)
        assert prompts and source.name in prompts[0]
        assert store.runs(session) == []
        assert window.worker is None
        assert window.composer.toPlainText() == '只审核本轮报告'
    finally:
        window.client = None
        window.close()
