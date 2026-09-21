import json
import os
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
    window.import_files([path])  # Explicitly select the current attachment, not project history.
    window.composer.setPlainText("检查这些资料")
    from asset_based_agent.technical_platform.skills import PREFLIGHT
    window.execute_plan('检查这些资料', PREFLIGHT)
    assert window.sidebar.isEnabled()
    assert not window.send.isEnabled()
    registered = window.task_manager.active()
    assert len(registered) == 1
    assert registered[0].task_id == window.run_id
    assert registered[0].session_id == session
    assert registered[0].owner == 'tester'
    deadline = time.monotonic() + 15
    while window.worker is not None and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.01)
    assert window.worker is None
    assert window.task_manager.active() == ()
    assert json.loads(store.run(window.run_id)["snapshot"])["user_request"] == "检查这些资料"
    with store.connect() as db:
        assert db.execute('SELECT revoked FROM execution_authorizations WHERE run=?',
                          (window.run_id,)).fetchone()[0] == 0
        assert db.execute('SELECT COUNT(*) FROM execution_results WHERE run=?',
                          (window.run_id,)).fetchone()[0] == 1
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
    window.connect_service = lambda: False
    window.submit()
    assert store.runs(session) == []
    assert window.composer.toPlainText() == '开始审核'
    assert store.messages(session) == []
    window.close()


def test_opening_session_reconciles_terminal_step_without_executing(tmp_path):
    from test_event_store import prepared

    from asset_based_agent.technical_platform.event_store import ExecutionStore
    app = QApplication.instance() or QApplication([])
    assert app is not None
    store, run, _, events = prepared(tmp_path)
    events.claim(run, 'execute')
    store.transition(run, 'validating', 'synthetic')
    store.transition(run, 'succeeded', 'synthetic')
    window = PlatformWindow(store)
    window.reload_projects(store.projects()[0]['id'])
    assert [event['kind'] for event in ExecutionStore(store).events(run)] == ['running', 'succeeded']
    assert window.worker is None
    window.close()


def test_worker_pins_project_store_before_catalog_changes(tmp_path):
    from asset_based_agent.technical_platform.app import TaskWorker
    from asset_based_agent.technical_platform.project_catalog import ProjectCatalog
    app = QApplication.instance() or QApplication([])
    assert app is not None
    catalog = ProjectCatalog(tmp_path / 'index.sqlite', 'alice')
    first, second = tmp_path / 'first', tmp_path / 'second'
    first.mkdir()
    second.mkdir()
    catalog.create_project('first', first)
    bound = catalog.active
    worker = TaskWorker(catalog, 'not-started')
    catalog.create_project('second', second)
    assert worker.store is bound
    assert worker.store is not catalog.active
    worker.deleteLater()


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
