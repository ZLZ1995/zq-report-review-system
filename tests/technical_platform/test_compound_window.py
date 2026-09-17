import os
import time
from copy import deepcopy

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import pytest
from PySide6.QtWidgets import QApplication
from test_compound_task import prepared

from asset_based_agent.technical_platform.app import PlatformWindow


@pytest.mark.parametrize('accept', [False, True, 'model_changed', 'revision_changed'])
def test_dialogue_compound_plan_confirmation_and_real_execution(tmp_path, accept):
    app = QApplication.instance() or QApplication([])
    store, session, fixture = prepared(tmp_path)
    calls, confirmations = [], []
    class Client:
        access_token = 'synthetic'
        def understand_task(self, payload, *, cancel=None):
            calls.append('understand')
            result = deepcopy(fixture['planning_request']['understanding'])
            result['evidence_message_ids'] = [payload['message_id']]
            return result
        def propose_plan(self, payload, *, cancel=None):
            calls.append('plan')
            result = deepcopy(fixture['plan_proposal'])
            result['request_id'] = payload['request']['request_id']
            return result
    window = PlatformWindow(store, client=Client(), models=[{'model_id': 'm', 'display_name': 'Synthetic'}])
    window.reload_projects(fixture['project_id'])
    window.import_files([tmp_path / 'source.xlsx'])
    def confirm(snapshot):
        confirmations.append(snapshot)
        if accept == 'model_changed':
            window.model_combo.addItem('other', 'other')
            window.model_combo.setCurrentIndex(window.model_combo.count() - 1)
        elif accept == 'revision_changed':
            from asset_based_agent.technical_platform.conversation_state import (
                ConversationState,
            )
            state = ConversationState(store)
            state.start(session, expected_revision=state.read(session)['revision'])
        return accept is not False
    window.confirm_compound_plan = confirm
    try:
        window.composer.setPlainText('生成后检查生成的文件')
        window.submit()
        deadline = time.monotonic() + 30
        while window.worker is not None and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(.01)
        assert window.worker is None
        assert calls == ['understand', 'plan']
        assert len(confirmations) == 1
        if accept is True:
            assert store.run(window.run_id)['state'] == 'succeeded'
            assert '组合任务完成' in window.transcript.toPlainText()
            assert 'history_fragment.docx' in window.transcript.toPlainText()
            assert 'zq-step-artifact:' in window.transcript.toHtml()
            from asset_based_agent.technical_platform.task_recovery import (
                reconcile_execution,
            )
            assert reconcile_execution(store, window.run_id) == 'succeeded'
        else:
            assert not store.runs(session)
            assert not (tmp_path / 'runs').exists()
    finally:
        if window.worker is not None:
            window.worker.cancel.set()
            window.worker.wait(10000)
            app.processEvents()
        window.client = None
        window.close()


def test_cancelled_planning_response_does_not_become_executable(tmp_path):
    from types import SimpleNamespace

    from asset_based_agent.agent_contracts import UnderstandingRequest
    from asset_based_agent.technical_platform.routing import UnderstandingWorker
    _, _, fixture = prepared(tmp_path)
    class Client:
        def understand_task(self, payload, *, cancel=None):
            return fixture['planning_request']['understanding']
        def propose_plan(self, payload, *, cancel=None):
            cancel.set()
            return fixture['plan_proposal']
    worker = UnderstandingWorker(Client(), SimpleNamespace(
        request=UnderstandingRequest.model_validate(fixture['planning_request']['request'])))
    worker.run()
    assert worker.proposal is None
    assert '取消' in worker.error


def test_compound_artifact_link_rechecks_scope_and_hash(tmp_path):
    import threading

    from asset_based_agent.technical_platform.execution import execute_task
    from asset_based_agent.technical_platform.permissions import PermissionService
    from asset_based_agent.technical_platform.plan_results import step_artifact_path
    store, session, snapshot = prepared(tmp_path)
    run = store.start_run(session, snapshot)
    PermissionService(store).authorize(run, snapshot, confirmed=True)
    execute_task(store, run, threading.Event(), lambda _: None)
    path = step_artifact_path(store, session, run, 0, 0)
    assert path.name == 'history_fragment.docx'
    with pytest.raises(PermissionError):
        step_artifact_path(store, 'other-session', run, 0, 0)
    with pytest.raises(ValueError):
        step_artifact_path(store, session, run, -1, 0)
    path.write_bytes(b'synthetic changed artifact')
    with pytest.raises(ValueError, match='changed'):
        step_artifact_path(store, session, run, 0, 0)


def test_plan_confirmation_uses_readonly_plain_text_and_exact_scope(tmp_path):
    from asset_based_agent.technical_platform.plan_confirmation import (
        PlanConfirmationDialog,
    )
    app = QApplication.instance() or QApplication([])
    assert app is not None
    _, _, snapshot = prepared(tmp_path)
    snapshot['execution_plan']['steps'][0]['goal'] = '<script>not executable</script>'
    dialog = PlanConfirmationDialog(snapshot, tmp_path)
    text = dialog.details.toPlainText()
    assert '<script>not executable</script>' in text
    assert 'source.xlsx' in text and '不改原件' in text and str(tmp_path) in text
    assert dialog.details.isReadOnly()
    dialog.close()
