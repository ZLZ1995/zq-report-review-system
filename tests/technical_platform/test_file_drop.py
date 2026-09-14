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
