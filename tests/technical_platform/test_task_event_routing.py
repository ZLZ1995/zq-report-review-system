import os

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtWidgets import QApplication

from asset_based_agent.technical_platform.app import PlatformWindow, TaskWorker
from asset_based_agent.technical_platform.store import PlatformStore


def test_worker_events_follow_original_store_after_visible_project_changes(tmp_path):
    app = QApplication.instance() or QApplication([])
    first = PlatformStore(tmp_path / 'first.sqlite', 'alice')
    project = first.create_project('first')
    session = first.create_session(project)
    run = first.start_run(session, {'files': []})
    first.transition(run, 'failed', 'context: ValueError')
    window = PlatformWindow(first)
    window.reload_projects(project)
    window.run_id = run
    worker = window.register_task_worker(TaskWorker(first, run, window))
    second = PlatformStore(tmp_path / 'second.sqlite', 'alice')
    other_project = second.create_project('second')
    other_session = second.create_session(other_project)
    window.store = second
    window.project_id, window.session_id, window.run_id = other_project, other_session, None
    window.status.setText('OTHER_SESSION')
    worker.progress.emit('PRIVATE_PROGRESS')
    worker.output.emit([{'description': 'ORIGINAL_ISSUE'}])
    worker.failed.emit('sk-NEVER-DISPLAY')
    app.processEvents()
    assert any('ORIGINAL_ISSUE' in item['text'] for item in first.messages(session))
    assert any('上下文构建' in item['text'] for item in first.messages(session))
    assert second.messages(other_session) == []
    assert window.status.text() == 'OTHER_SESSION'
    assert 'ORIGINAL_ISSUE' not in window.transcript.toPlainText()
    assert all('sk-NEVER-DISPLAY' not in item['text'] for item in first.messages(session))
    worker.finished.emit()
    app.processEvents()
    assert window.task_manager.active() == ()
    assert window.worker is None
    window.close()


def test_background_completion_and_late_output_are_isolated(tmp_path):
    app = QApplication.instance() or QApplication([])
    store = PlatformStore(tmp_path / 'state.sqlite', 'alice')
    project = store.create_project('project')
    first = store.create_session(project)
    second = store.create_session(project)
    run = store.start_run(first, {'files': []})
    window = PlatformWindow(store)
    window.project_id, window.session_id, window.run_id = project, first, run
    worker = window.register_task_worker(TaskWorker(store, run, window))
    window.session_id = second
    worker.completed.emit({'kind': 'review', 'files': [], 'issues': [{'description': 'DONE_ISSUE'}]})
    app.processEvents()
    assert any('DONE_ISSUE' in item['text'] for item in store.messages(first))
    assert store.messages(second) == []
    worker.finished.emit()
    # Finished has released the registration: queued/late output is ignored.
    worker.output.emit([{'description': 'LATE_ISSUE'}])
    app.processEvents()
    assert not any('LATE_ISSUE' in item['text'] for item in store.messages(first))
    window.close()
