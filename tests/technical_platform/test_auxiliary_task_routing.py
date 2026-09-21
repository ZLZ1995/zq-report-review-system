import os

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import pytest
from PySide6.QtWidgets import QApplication
from test_agent_controller import response

from asset_based_agent.technical_platform.agent_controller import AgentController
from asset_based_agent.technical_platform.annotations import AnnotationWorker
from asset_based_agent.technical_platform.app import PlatformWindow
from asset_based_agent.technical_platform.routing import UnderstandingWorker
from asset_based_agent.technical_platform.store import PlatformStore


@pytest.mark.parametrize('cancelled', [False, True])
def test_understanding_finishes_in_original_conversation(tmp_path, cancelled):
    app = QApplication.instance() or QApplication([])
    store = PlatformStore(tmp_path / 'state.sqlite', 'alice')
    project = store.create_project('project')
    first, second = store.create_session(project), store.create_session(project)
    window = PlatformWindow(store)
    window.project_id, window.session_id = project, first
    controller = AgentController(store)
    pending = controller.prepare(first, '解释审核', model_id='m', selected_ids=[])
    worker = UnderstandingWorker(None, pending, window)
    worker.controller = controller
    worker.plan = response(pending.request)
    window.register_understanding_worker(worker)
    if cancelled:
        window.cancel_run()
        assert worker.cancel.is_set()
    window.session_id = second
    window.status.setText('OTHER_SESSION')
    worker.finished.emit()
    app.processEvents()
    text = '\n'.join(item['text'] for item in store.messages(first))
    assert ('任务理解已取消' if cancelled else '审核默认只读') in text
    assert store.messages(second) == []
    assert window.status.text() == 'OTHER_SESSION'
    assert window.worker is None
    assert window.task_manager.active() == ()
    assert not store.runs(first)
    window.close()


@pytest.mark.parametrize('outcome', ['success', 'error', 'cancelled'])
def test_annotation_finish_does_not_use_new_visible_session_or_prompt_it(tmp_path, outcome):
    app = QApplication.instance() or QApplication([])
    store = PlatformStore(tmp_path / 'state.sqlite', 'alice')
    project = store.create_project('project')
    first, second = store.create_session(project), store.create_session(project)
    run = store.start_run(first, {'files': []})
    window = PlatformWindow(store)
    window.project_id, window.session_id, window.run_id = project, first, run
    worker = AnnotationWorker(store, run, [], str(tmp_path), window)
    worker.result = ([{'issue': 1, 'reason': 'SYNTHETIC_RESULT'}], ['synthetic.docx'])
    if outcome == 'error':
        worker.error, worker.result = 'SYNTHETIC_FAILURE', None
    elif outcome == 'cancelled':
        worker.cancel.set()
        worker.result = None
    window.register_annotation_worker(worker)
    window.session_id = second
    window.status.setText('OTHER_SESSION')
    offered = []
    window.offer_annotations = lambda *args, **kwargs: offered.append(args)
    worker.finished.emit()
    app.processEvents()
    expected = {'success': 'SYNTHETIC_RESULT', 'error': 'SYNTHETIC_FAILURE', 'cancelled': '批注已停止'}[outcome]
    assert any(expected in item['text'] for item in store.messages(first))
    assert store.messages(second) == []
    assert window.status.text() == 'OTHER_SESSION'
    assert not offered
    assert window.task_manager.active() == ()
    window.close()
