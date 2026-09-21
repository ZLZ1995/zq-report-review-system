import json

import pytest
from test_execution import make_run as execution_fixture


def make_run(*args, **kwargs):
    return execution_fixture(*args, **kwargs, authorize=False)


def test_grant_requires_confirmation_and_is_bound_to_recorded_snapshot(tmp_path):
    from asset_based_agent.technical_platform.permissions import PermissionService
    store, run, _ = make_run(tmp_path)
    service = PermissionService(store)
    snapshot = json.loads(store.run(run)['snapshot'])
    with pytest.raises(PermissionError):
        service.authorize(run, snapshot, confirmed=False)
    with pytest.raises(PermissionError):
        service.verify(run)
    service.authorize(run, snapshot, confirmed=True)
    service.verify(run)
    changed = {**snapshot, 'user_request': 'different task'}
    with pytest.raises(PermissionError):
        service.authorize(run, changed, confirmed=True)


@pytest.mark.parametrize('field,value', [('model', 'other'), ('user_request', 'changed'),
                                      ('permissions', {'modify_originals': True}), ('files', [])])
def test_changed_scope_or_action_invalidates_permission(tmp_path, field, value):
    from asset_based_agent.technical_platform.permissions import PermissionService
    store, run, _ = make_run(tmp_path)
    service = PermissionService(store)
    snapshot = json.loads(store.run(run)['snapshot'])
    service.authorize(run, snapshot, confirmed=True)
    snapshot[field] = value
    with store.connect() as db:
        db.execute('UPDATE runs SET snapshot=? WHERE id=?', (json.dumps(snapshot), run))
    with pytest.raises(PermissionError):
        service.verify(run)


def test_revocation_and_other_account_cannot_reuse_grant(tmp_path):
    from asset_based_agent.technical_platform.permissions import PermissionService
    from asset_based_agent.technical_platform.store import PlatformStore
    store, run, _ = make_run(tmp_path)
    service = PermissionService(store)
    service.authorize(run, json.loads(store.run(run)['snapshot']), confirmed=True)
    other = PermissionService(PlatformStore(store.path, 'bob'))
    with pytest.raises(PermissionError):
        other.verify(run)
    with pytest.raises(PermissionError):
        other.revoke(run)
    service.revoke(run)
    with pytest.raises(PermissionError):
        service.verify(run)


def test_required_grant_checked_before_tool_entry(tmp_path, monkeypatch):
    import threading

    from asset_based_agent.technical_platform import execution
    store, run, _ = make_run(tmp_path, change=lambda s: s.update(requires_authorization=True))
    monkeypatch.setattr(execution, 'preflight', lambda *a, **k: pytest.fail('unauthorized tool call'))
    with pytest.raises(PermissionError):
        execution.execute_task(store, run, threading.Event(), lambda _: None)


def test_moving_database_to_new_output_root_requires_fresh_consent(tmp_path):
    import shutil

    from asset_based_agent.technical_platform.permissions import PermissionService
    from asset_based_agent.technical_platform.store import PlatformStore
    store, run, _ = make_run(tmp_path)
    service = PermissionService(store)
    service.authorize(run, json.loads(store.run(run)['snapshot']), confirmed=True)
    moved = tmp_path / 'different-output-root'
    moved.mkdir()
    shutil.copyfile(store.path, moved / 'db.sqlite')
    relocated = PermissionService(PlatformStore(moved / 'db.sqlite', 'alice'))
    with pytest.raises(PermissionError):
        relocated.verify(run)
    service.verify(run)


def test_dropping_required_flag_does_not_bypass_existing_receipt(tmp_path):
    import threading

    from asset_based_agent.technical_platform.execution import execute_task
    from asset_based_agent.technical_platform.permissions import PermissionService
    store, run, _ = make_run(tmp_path, change=lambda s: s.update(requires_authorization=True))
    snapshot = json.loads(store.run(run)['snapshot'])
    PermissionService(store).authorize(run, snapshot, confirmed=True)
    snapshot.pop('requires_authorization')
    with store.connect() as db:
        db.execute('UPDATE runs SET snapshot=? WHERE id=?', (json.dumps(snapshot), run))
    with pytest.raises(PermissionError):
        execute_task(store, run, threading.Event(), lambda _: None)


def test_v1_history_cannot_receive_new_authorization(tmp_path):
    from asset_based_agent.technical_platform.permissions import PermissionService
    store, run, _ = make_run(tmp_path, change=lambda s: s.update(schema_version=1))
    with pytest.raises(PermissionError):
        PermissionService(store).authorize(run, json.loads(store.run(run)['snapshot']), confirmed=True)


def test_v2_cannot_bypass_consent_by_omitting_flag(tmp_path):
    import threading

    from asset_based_agent.technical_platform.execution import execute_task
    store, run, _ = make_run(tmp_path, change=lambda s: s.pop('requires_authorization'))
    with pytest.raises(PermissionError):
        execute_task(store, run, threading.Event(), lambda _: None)
