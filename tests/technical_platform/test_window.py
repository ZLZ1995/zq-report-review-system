import os
import json
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from openpyxl import Workbook
from PySide6.QtWidgets import QApplication

from asset_based_agent.technical_platform.app import PlatformWindow
from asset_based_agent.technical_platform.skills import digest
from asset_based_agent.technical_platform.store import PlatformStore


def test_project_chat_preflight_and_result_restore(tmp_path):
    app = QApplication.instance() or QApplication([])
    store = PlatformStore(tmp_path / "state.sqlite", "tester")
    project = store.create_project("电子设备评估")
    session = store.create_session(project, "资料核对")
    path = tmp_path / "detail.xlsx"
    book = Workbook()
    book.active["A1"] = "电子设备"
    book.save(path)
    store.add_file(project, path, digest(path))
    window = PlatformWindow(store)
    window.reload_projects(project)
    window.composer.setPlainText("检查这些资料")
    window.submit()
    assert not window.sidebar.isEnabled()
    deadline = time.monotonic() + 15
    while window.worker is not None and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.01)
    assert window.worker is None
    assert json.loads(store.run(window.run_id)["snapshot"])["user_request"] == "检查这些资料"
    assert "原文件未变化" in window.transcript.toPlainText()
    assert "detail.xlsx" in window.transcript.toPlainText()
    assert [window.details.tabText(i) for i in range(window.details.count())] == ["文件", "记忆"]
    window.close()
    reopened = PlatformWindow(store)
    reopened.reload_projects(project)
    assert reopened.session_id == session
    assert "detail.xlsx" in reopened.transcript.toPlainText()
    assert "检查这些资料" in reopened.transcript.toPlainText()
    reopened.close()


def test_empty_project_cannot_start_run(tmp_path):
    app = QApplication.instance() or QApplication([])
    assert app is not None
    store = PlatformStore(tmp_path / "state.sqlite", "tester")
    project = store.create_project("空项目")
    session = store.create_session(project)
    window = PlatformWindow(store)
    window.reload_projects(project)
    window.composer.setPlainText("开始审核")
    window.submit()
    assert store.runs(session) == []
    assert "先添加资料" in window.transcript.toPlainText()
    window.close()


def test_failure_diagnostic_is_visible_and_restored_without_exception_secret(tmp_path):
    app = QApplication.instance() or QApplication([])
    assert app is not None
    store = PlatformStore(tmp_path / "state.sqlite", "tester")
    project = store.create_project("failure")
    session = store.create_session(project)
    run = store.start_run(session, {"files": []})
    store.transition(run, "failed", "context: ValueError")
    window = PlatformWindow(store)
    window.reload_projects(project)
    window.run_id = run
    window.failed("sk-PRIVATE-EXCEPTION")
    assert "上下文构建" in window.transcript.toPlainText()
    assert "sk-PRIVATE" not in window.transcript.toPlainText()
    window.close()
    reopened = PlatformWindow(store)
    reopened.reload_projects(project)
    assert "上下文构建" in reopened.transcript.toPlainText()
    assert run in reopened.transcript.toPlainText()
    reopened.close()


def test_incremental_output_persists_once_per_run(tmp_path):
    app = QApplication.instance() or QApplication([])
    assert app is not None
    store = PlatformStore(tmp_path / "state.sqlite", "tester")
    project = store.create_project("Streaming")
    session = store.create_session(project)
    window = PlatformWindow(store)
    window.reload_projects(project)
    window.run_id = store.start_run(session, {"files": []})
    issues = [{"source_file_name": "test.docx", "description": "BATCH_ONE_OUTPUT", "location": {"page": None, "paragraph": 1}}]
    window.receive_output(issues)
    window.receive_output(issues)
    assert window.transcript.toPlainText().count("BATCH_ONE_OUTPUT") == 1
    assert "None" not in window.transcript.toPlainText()
    window.close()
    reopened = PlatformWindow(store)
    reopened.reload_projects(project)
    assert "BATCH_ONE_OUTPUT" in reopened.transcript.toPlainText()
    reopened.close()
