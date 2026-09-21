import json
from threading import Event

import pytest
from test_browser_upload_source import source


def ready(tmp_path, actions=None):
    from asset_based_agent.technical_platform.browser_task_spec import (
        build_browser_task_spec,
    )
    from asset_based_agent.technical_platform.browser_upload_permissions import (
        UploadScope,
    )
    from asset_based_agent.technical_platform.browser_upload_preparation import (
        prepare_upload,
    )
    from asset_based_agent.technical_platform.event_store import ExecutionStore
    from asset_based_agent.technical_platform.execution_plan import ExecutionPlan
    from asset_based_agent.technical_platform.permissions import PermissionService
    from asset_based_agent.technical_platform.task_spec import snapshot_identity
    store, session, producer, _, version = source(tmp_path)
    reference = {'run_id': producer, 'kind': 'generation', 'index': 0, 'sha256': version}
    artifact = prepare_upload(store, session, reference, Event())
    snapshot = build_browser_task_spec(store, session, 'Upload to synthetic object', model='test',
        origins=['https://example.com'], actions=actions or ['observe', 'upload'],
        environment='test').to_snapshot()
    run = store.start_run(session, snapshot)
    PermissionService(store).authorize(run, snapshot, confirmed=True)
    store.transition(run, 'running', 'synthetic')
    plan = ExecutionPlan.model_validate(snapshot['execution_plan'])
    events = ExecutionStore(store); events.register(plan)
    claim = events.claim(run, plan.steps[0].step_id)
    scope = UploadScope(identity=snapshot_identity(snapshot), step_id=plan.steps[0].step_id,
        claim_token=claim, revision=1, environment='test', origin='https://example.com',
        tab_id='tab', page_version=1, object_label='Synthetic project 001', field_id='file-1',
        receipt_id='pending', artifact=artifact)
    return store, run, scope, reference


def test_upload_durable_authorization_is_scoped_and_single_use(tmp_path):
    from asset_based_agent.technical_platform.browser_upload_authorization import (
        UploadAuthorization,
    )
    store, run, scope, reference = ready(tmp_path)
    service = UploadAuthorization(store)
    permit = service.authorize(scope, reference, confirmed=True, cancel=Event())
    service.consume(permit, permit.scope, active=True)
    with pytest.raises(PermissionError): service.consume(permit, permit.scope, active=True)
    with store.connect() as db:
        row = db.execute('SELECT * FROM browser_action_authorizations WHERE run=?', (run,)).fetchone()
    assert row['consumed'] == 1
    assert scope.artifact.path not in json.dumps(dict(row))


def test_upload_restart_cannot_replay_unknown_delivery(tmp_path):
    from asset_based_agent.technical_platform.browser_upload_authorization import (
        UploadAuthorization,
    )
    from asset_based_agent.technical_platform.store import PlatformStore
    store, _, scope, reference = ready(tmp_path)
    service = UploadAuthorization(store)
    permit = service.authorize(scope, reference, confirmed=True, cancel=Event())
    service.consume(permit, permit.scope, active=True)
    service.close()
    restarted = UploadAuthorization(PlatformStore(store.path, store.owner))
    changed_page = scope.model_copy(update={'page_version': 2, 'field_id': 'file-2'})
    with pytest.raises(PermissionError, match='reconcile'):
        retry = restarted.authorize(changed_page, reference, confirmed=True, cancel=Event())
        restarted.consume(retry, retry.scope, active=True)
    # A different explicit business object is not the same operation.
    other = changed_page.model_copy(update={'object_label': 'Synthetic project 002'})
    permit = restarted.authorize(other, reference, confirmed=True, cancel=Event())
    restarted.consume(permit, permit.scope, active=True)


@pytest.mark.parametrize('case', ['no_upload', 'refused', 'revoked', 'changed'])
def test_upload_authorization_rejects_scope_revoke_or_file_change(tmp_path, case):
    from pathlib import Path

    from asset_based_agent.technical_platform.browser_upload_authorization import (
        UploadAuthorization,
    )
    from asset_based_agent.technical_platform.permissions import PermissionService
    store, run, scope, reference = ready(tmp_path, ['observe', 'click'] if case == 'no_upload' else None)
    service = UploadAuthorization(store)
    if case in {'no_upload', 'refused'}:
        with pytest.raises(PermissionError):
            service.authorize(scope, reference, confirmed=case != 'refused', cancel=Event())
        return
    permit = service.authorize(scope, reference, confirmed=True, cancel=Event())
    if case == 'revoked': PermissionService(store).revoke(run)
    if case == 'changed': Path(scope.artifact.path).write_bytes(b'changed')
    with pytest.raises((PermissionError, ValueError)):
        service.consume(permit, permit.scope, active=True)


def test_upload_two_prepared_permits_commit_only_once(tmp_path):
    from concurrent.futures import ThreadPoolExecutor

    from asset_based_agent.technical_platform.browser_upload_authorization import (
        UploadAuthorization,
    )
    store, _, scope, reference = ready(tmp_path)
    first, second = UploadAuthorization(store), UploadAuthorization(store)
    permits = [first.authorize(scope, reference, confirmed=True, cancel=Event()),
               second.authorize(scope.model_copy(update={'page_version': 2}), reference,
                                confirmed=True, cancel=Event())]
    def commit(pair):
        service, permit = pair
        try:
            service.consume(permit, permit.scope, active=True)
            return True
        except PermissionError:
            return False
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sum(pool.map(commit, zip((first, second), permits))) == 1
    with store.connect() as db:
        rows = db.execute('SELECT * FROM browser_upload_attempts').fetchall()
    assert len(rows) == 1 and rows[0]['state'] == 'unknown'
    assert scope.artifact.path not in json.dumps(dict(rows[0]))


def test_native_target_identity_prevents_label_based_replay(tmp_path):
    from asset_based_agent.technical_platform.browser_upload_authorization import (
        UploadAuthorization,
    )
    from asset_based_agent.technical_platform.browser_upload_permissions import (
        UploadScope,
    )
    store, _, scope, reference = ready(tmp_path)
    scope = UploadScope.model_validate({**scope.model_dump(), 'target_key': 'a' * 64})
    service = UploadAuthorization(store)
    permit = service.authorize(scope, reference, confirmed=True, cancel=Event())
    service.consume(permit, permit.scope, active=True)
    renamed = scope.model_copy(update={'object_label': 'Model renamed the same project', 'page_version': 2})
    with pytest.raises(PermissionError, match='reconcile'):
        UploadAuthorization(store).authorize(renamed, reference, confirmed=True, cancel=Event())


def test_old_unknown_attempt_cannot_be_bypassed_by_new_native_identity(tmp_path):
    from asset_based_agent.technical_platform.browser_upload_authorization import (
        UploadAuthorization,
    )
    from asset_based_agent.technical_platform.browser_upload_permissions import (
        UploadScope,
    )
    store, _, scope, reference = ready(tmp_path)
    service = UploadAuthorization(store)
    permit = service.authorize(scope, reference, confirmed=True, cancel=Event())
    service.consume(permit, permit.scope, active=True)
    upgraded = UploadScope.model_validate({**scope.model_dump(), 'target_key': 'b' * 64,
                                          'object_label': 'renamed', 'page_version': 2})
    with pytest.raises(PermissionError, match='reconcile'):
        UploadAuthorization(store).authorize(upgraded, reference, confirmed=True, cancel=Event())
