import json

import pytest

from asset_based_agent.technical_platform.execution_plan import ExecutionPlan
from asset_based_agent.technical_platform.permissions import PermissionService
from asset_based_agent.technical_platform.store import PlatformStore


def make_browser_run(tmp_path, *, actions=None, origins=None, authorize=True):
    from asset_based_agent.technical_platform.browser_task_spec import (
        build_browser_task_spec,
    )
    store = PlatformStore(tmp_path / 'browser.sqlite', 'alice')
    project = store.create_project('Browser project')
    session = store.create_session(project)
    snapshot = build_browser_task_spec(
        store, session, 'Inspect the specified website', model='test-model',
        origins=origins or ['https://example.com'],
        actions=actions or ['observe', 'navigate', 'fill'], environment='test').to_snapshot()
    run = store.start_run(session, snapshot)
    if authorize:
        PermissionService(store).authorize(run, snapshot, confirmed=True)
    return store, run, project


def test_browser_task_has_no_fake_files_and_uses_existing_plan_store(tmp_path):
    from asset_based_agent.technical_platform.event_store import ExecutionStore
    store, run, _ = make_browser_run(tmp_path)
    snapshot = json.loads(store.run(run)['snapshot'])
    assert snapshot['files'] == snapshot['selected_files'] == []
    assert snapshot['permissions']['read_selected_files'] is False
    assert snapshot['permissions']['upload_raw_files'] is False
    assert snapshot['permissions']['modify_originals'] is False
    plan = ExecutionPlan.model_validate(snapshot['execution_plan'])
    assert plan.input_versions == {} and plan.steps[0].inputs == []
    assert plan.steps[0].tool == 'browser.execute'
    store.transition(run, 'running', 'start')
    executions = ExecutionStore(store)
    executions.register(plan)
    assert executions.claim(run, plan.steps[0].step_id)


@pytest.mark.parametrize('changes', [
    {'origins':['http://example.com']}, {'origins':['https://example.com/path']},
    {'origins':[]}, {'actions':[]}, {'actions':['arbitrary_javascript']},
    {'environment':'other'}, {'model':''},
])
def test_browser_task_rejects_invalid_scope(tmp_path, changes):
    from asset_based_agent.technical_platform.browser_task_spec import (
        build_browser_task_spec,
    )
    store = PlatformStore(tmp_path / 'db.sqlite', 'alice')
    session = store.create_session(store.create_project('one'))
    values = {'model':'test-model', 'origins':['https://example.com'],
              'actions':['observe'], 'environment':'test'}
    values.update(changes)
    with pytest.raises((ValueError, PermissionError)):
        build_browser_task_spec(store, session, 'Inspect website', **values)


def test_file_plan_still_rejects_empty_inputs(tmp_path):
    from test_execution import make_run
    store, run, _ = make_run(tmp_path)
    plan = json.loads(store.run(run)['snapshot'])['execution_plan']
    plan['steps'][0]['inputs'] = []
    plan['input_versions'] = {}
    with pytest.raises(ValueError): ExecutionPlan.model_validate(plan)


def test_file_task_cannot_issue_browser_receipt(tmp_path):
    from hashlib import sha256

    from test_execution import make_run

    from asset_based_agent.technical_platform.browser_action_request import (
        BrowserActionRequest,
    )
    from asset_based_agent.technical_platform.event_store import ExecutionStore
    from asset_based_agent.technical_platform.task_spec import snapshot_identity
    store, run, _ = make_run(tmp_path)
    snapshot = json.loads(store.run(run)['snapshot'])
    plan = ExecutionPlan.model_validate(snapshot['execution_plan'])
    store.transition(run, 'running', 'start')
    executions = ExecutionStore(store); executions.register(plan)
    claim = executions.claim(run, plan.steps[0].step_id)
    request = BrowserActionRequest(identity=snapshot_identity(snapshot), step_id=plan.steps[0].step_id,
        revision=1, claim_token=claim, environment='test', tab_id='tab', page_version=0,
        origin='https://example.com', action='fill', target='one', payload_sha256=sha256(b'value').hexdigest())
    with pytest.raises(PermissionError):
        PermissionService(store).authorize_browser_action(request, confirmed=True)


@pytest.mark.parametrize('change', [
    {'origin':'https://other.example'}, {'action':'login'}, {'environment':'production'},
])
def test_browser_action_cannot_expand_task_scope(tmp_path, change):
    from test_browser_action_receipts import ready
    _, _, service, request = ready(tmp_path)
    with pytest.raises(PermissionError):
        service.authorize_browser_action(request.model_copy(update=change), confirmed=True)


def test_browser_task_cannot_take_another_owners_session(tmp_path):
    from asset_based_agent.technical_platform.browser_task_spec import (
        build_browser_task_spec,
    )
    store, run, _ = make_browser_run(tmp_path)
    session = store.run(run)['session']
    other = PlatformStore(store.path, 'bob', create=False)
    with pytest.raises(PermissionError):
        build_browser_task_spec(other, session, 'Read website', model='test',
                                origins=['https://example.com'], actions=['observe'], environment='test')
