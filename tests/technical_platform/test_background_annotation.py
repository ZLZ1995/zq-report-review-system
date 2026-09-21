import json
import os

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import pytest
from PySide6.QtWidgets import QApplication, QMessageBox

from asset_based_agent.technical_platform.annotation_followup import ensure_questions
from asset_based_agent.technical_platform.app import PlatformWindow, TaskWorker
from asset_based_agent.technical_platform.store import PlatformStore


def finished_review(store, session, issues):
    run = store.start_run(session, {'files': []})
    store.claim_run(run)
    store.save_result(run, {'kind': 'review', 'issues': issues})
    store.transition(run, 'validating', 'synthetic')
    store.transition(run, 'succeeded', 'synthetic')
    return run


def test_background_review_persists_question_once_without_wrong_chat_dialog(tmp_path, monkeypatch):
    qt = QApplication.instance() or QApplication([])
    store = PlatformStore(tmp_path / 'state.sqlite', 'alice')
    project = store.create_project('project')
    first, other = store.create_session(project), store.create_session(project)
    run = finished_review(store, first, [{'description': 'synthetic'}])
    window = PlatformWindow(store)
    window.project_id, window.session_id = project, first
    worker = window.register_task_worker(TaskWorker(store, run, window))
    window.session_id = other
    dialogs = []
    monkeypatch.setattr(QMessageBox, 'question', lambda *args: dialogs.append(True) or QMessageBox.StandardButton.No)
    worker.finished.emit()
    qt.processEvents()
    assert not dialogs
    assert store.messages(other) == []
    assert sum('是否生成带问题标记和批注' in m['text'] for m in store.messages(first)) == 1
    assert json.loads(store.run(run)['result'])['annotation_prompted'] is True
    window.session_id = first
    window.offer_annotations(run)
    assert not dialogs
    window.close()
    reopened = PlatformWindow(store)
    reopened.project_id, reopened.session_id = project, first
    reopened.render_messages()
    assert '是否生成带问题标记和批注' in reopened.transcript.toPlainText()
    reopened.close()
    assert not list(tmp_path.rglob('*.docx'))


def test_question_flag_and_message_rollback_together(tmp_path):
    store = PlatformStore(tmp_path / 'state.sqlite', 'alice')
    session = store.create_session(store.create_project('project'))
    run = finished_review(store, session, [{'description': 'synthetic'}])
    with store.connect() as db:
        db.execute("CREATE TRIGGER reject_message BEFORE INSERT ON messages BEGIN SELECT RAISE(ABORT, 'synthetic'); END")
    import sqlite3
    with pytest.raises(sqlite3.IntegrityError):
        ensure_questions(store, run)
    assert not json.loads(store.run(run)['result']).get('annotation_prompted')
    with store.connect() as db:
        db.execute('DROP TRIGGER reject_message')
    assert ensure_questions(store, run) == [None]
    assert ensure_questions(store, run) == []
    assert len(store.messages(session)) == 1


def test_empty_review_and_other_account_cannot_create_question(tmp_path):
    store = PlatformStore(tmp_path / 'state.sqlite', 'alice')
    session = store.create_session(store.create_project('project'))
    empty = finished_review(store, session, [])
    assert ensure_questions(store, empty) == []
    assert store.messages(session) == []
    run = finished_review(store, session, [{'description': 'synthetic'}])
    other = PlatformStore(store.path, 'bob')
    with pytest.raises(PermissionError):
        ensure_questions(other, run)
    assert not json.loads(store.run(run)['result']).get('annotation_prompted')


def test_compound_question_preserves_step_results(tmp_path, monkeypatch):
    from test_step_delivery import reviewed
    store, session, run = reviewed(tmp_path, monkeypatch, with_issues=True)
    before = json.loads(store.run(run)['result'])['steps']
    assert ensure_questions(store, run) == [1]
    assert ensure_questions(store, run) == []
    after = json.loads(store.run(run)['result'])
    assert after['steps'] == before
    assert len(after['review_deliveries']) == 1
    assert sum('第 2 个步骤' in item['text'] for item in store.messages(session)) == 1
