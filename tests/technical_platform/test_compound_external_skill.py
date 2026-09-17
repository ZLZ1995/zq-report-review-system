import threading
from types import SimpleNamespace

import pytest
from test_compound_task import prepared
from test_skill_installation import make_package

from asset_based_agent.technical_platform.compound_task import build_compound_task_spec
from asset_based_agent.technical_platform.execution import execute_task
from asset_based_agent.technical_platform.permissions import PermissionService
from asset_based_agent.technical_platform.skill_installation import SkillInstallation


def external_task(tmp_path):
    store, session, original = prepared(tmp_path, remote=True)
    manager = SkillInstallation(store)
    package = manager.install(make_package(tmp_path, rules='SYNTHETIC_EXTERNAL_RULE'), confirmed=True)
    manager.activate('test.review', '1.0.0', confirmed=True)
    payload, proposal = original['planning_request'], original['plan_proposal']
    payload['request']['skills'][1]['id'] = 'test.review'
    payload['understanding']['skill_ids'][1] = 'test.review'
    proposal['steps'][1]['skill_id'] = 'test.review'
    snapshot = build_compound_task_spec(store, session, payload, proposal,
                                        original['planning_files'], revision=3).to_snapshot()
    return store, session, snapshot, manager, package


def test_external_compound_uses_pinned_rules_and_trusted_adapter(tmp_path, monkeypatch):
    from asset_based_agent.report_review_app.services import remote_review_llm
    from asset_based_agent.technical_platform.plan_confirmation import confirmation_text
    store, session, snapshot, manager, package = external_task(tmp_path)
    binding = snapshot['step_configs']['inspect']['external_skill']
    assert binding == {'id': 'test.review', 'version': '1.0.0', 'sha256': package.sha256}
    assert 'test.review' in confirmation_text(snapshot, tmp_path)
    calls = []

    class Provider:
        def __init__(self, client, *, model_id, skill_instructions):
            assert 'SYNTHETIC_EXTERNAL_RULE' in skill_instructions
            self.model_id, self.skill_instructions = model_id, skill_instructions
        def set_client_job_id(self, value):
            pass
        def review_batches(self, batches, progress_callback=None):
            calls.append(batches)
            return []

    monkeypatch.setattr(remote_review_llm, 'RemoteReviewLlm', Provider)
    run = store.start_run(session, snapshot)
    PermissionService(store).authorize(run, snapshot, confirmed=True)
    with pytest.raises(ValueError, match='未结束'):
        manager.disable('test.review', confirmed=True)
    result = execute_task(store, run, threading.Event(), lambda _: None,
                          client=SimpleNamespace(access_token='synthetic'))
    assert result['kind'] == 'plan' and len(calls) == 1
    manager.disable('test.review', confirmed=True)


@pytest.mark.parametrize('change', ['disable', 'version', 'rules', 'binding'])
def test_external_change_after_plan_never_starts_local_generation(tmp_path, change):
    store, session, snapshot, manager, _ = external_task(tmp_path)
    if change == 'disable':
        manager.disable('test.review', confirmed=True)
    elif change == 'version':
        manager.install(make_package(tmp_path, version='2.0.0'), confirmed=True)
        manager.activate('test.review', '2.0.0', confirmed=True)
    elif change == 'rules':
        snapshot['step_configs']['inspect']['skill_instructions'] = 'forged'
    else:
        snapshot['step_configs']['inspect']['external_skill']['sha256'] = '0' * 64
    run = store.start_run(session, snapshot)
    PermissionService(store).authorize(run, snapshot, confirmed=True)
    with pytest.raises((ValueError, PermissionError)):
        execute_task(store, run, threading.Event(), lambda _: None,
                     client=SimpleNamespace(access_token='synthetic'))
    assert not (tmp_path / 'runs' / run).exists()


def test_dialogue_routes_installed_external_rules_into_compound_execution(tmp_path, monkeypatch):
    import time
    from copy import deepcopy

    from PySide6.QtWidgets import QApplication

    from asset_based_agent.report_review_app.services import remote_review_llm
    from asset_based_agent.technical_platform.app import PlatformWindow
    app = QApplication.instance() or QApplication([])
    store, session, fixture, _, _ = external_task(tmp_path)
    calls = []

    class Client:
        access_token = 'synthetic'
        def understand_task(self, payload, *, cancel=None):
            assert 'test.review' in {s['id'] for s in payload['skills']}
            result = deepcopy(fixture['planning_request']['understanding'])
            result['evidence_message_ids'] = [payload['message_id']]
            return result
        def propose_plan(self, payload, *, cancel=None):
            result = deepcopy(fixture['plan_proposal'])
            result['request_id'] = payload['request']['request_id']
            return result

    class Provider:
        def __init__(self, client, *, model_id, skill_instructions):
            assert 'SYNTHETIC_EXTERNAL_RULE' in skill_instructions
            self.model_id, self.skill_instructions = model_id, skill_instructions
        def set_client_job_id(self, value):
            pass
        def review_batches(self, batches, progress_callback=None):
            calls.append(True)
            return []

    monkeypatch.setattr(remote_review_llm, 'RemoteReviewLlm', Provider)
    window = PlatformWindow(store, client=Client(), models=[{'model_id': 'm', 'display_name': 'Synthetic'}])
    window.reload_projects(store.session(session)['project'])
    window.import_files([tmp_path / 'source.xlsx'])
    monkeypatch.setattr(window, 'confirm_compound_plan', lambda snapshot: True)
    try:
        window.composer.setPlainText('生成文件后用外部规则审核')
        window.submit()
        deadline = time.monotonic() + 30
        while window.worker is not None and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(.01)
        assert window.worker is None
        assert calls == [True]
        assert store.run(window.run_id)['state'] == 'succeeded'
        assert 'zq-step-export:' in window.transcript.toHtml()
    finally:
        if window.worker is not None:
            window.worker.cancel.set()
            window.worker.wait(20000)
            app.processEvents()
        window.client = None
        window.close()
