import json
from hashlib import sha256

import pytest
from test_browser_task_spec import make_browser_run


def ready(tmp_path):
    from asset_based_agent.technical_platform.browser_action_request import (
        BrowserActionRequest,
    )
    from asset_based_agent.technical_platform.event_store import ExecutionStore
    from asset_based_agent.technical_platform.execution_plan import ExecutionPlan
    from asset_based_agent.technical_platform.permissions import PermissionService
    from asset_based_agent.technical_platform.task_spec import snapshot_identity
    store, run, _ = make_browser_run(tmp_path)
    snapshot=json.loads(store.run(run)['snapshot'])
    plan=ExecutionPlan.model_validate(snapshot['execution_plan'])
    store.transition(run,'running','start')
    executions=ExecutionStore(store); executions.register(plan)
    claim=executions.claim(run,plan.steps[0].step_id)
    request=BrowserActionRequest(identity=snapshot_identity(snapshot),step_id=plan.steps[0].step_id,
        revision=1,claim_token=claim,environment='test',tab_id='native-tab',page_version=1,origin='https://example.com',
        action='fill',target='observation:control-1',payload_sha256=sha256(b'approved-value').hexdigest())
    return store, run, PermissionService(store), request


def test_action_receipt_is_explicit_one_use_and_stores_no_values(tmp_path):
    store, _, service, request=ready(tmp_path)
    with pytest.raises(PermissionError): service.authorize_browser_action(request,confirmed=False)
    receipt=service.authorize_browser_action(request,confirmed=True)
    service.consume_browser_action(receipt,request)
    from asset_based_agent.technical_platform.permissions import PermissionService
    from asset_based_agent.technical_platform.store import PlatformStore
    reopened=PermissionService(PlatformStore(store.path,'alice',create=False))
    with pytest.raises(PermissionError): reopened.consume_browser_action(receipt,request)
    with store.connect() as db:
        assert 'approved-value' not in str(db.execute('SELECT * FROM browser_action_authorizations').fetchall())


def test_action_change_task_revoke_and_foreign_owner_fail_closed(tmp_path):
    store, run, service, request=ready(tmp_path)
    receipt=service.authorize_browser_action(request,confirmed=True)
    changed=request.model_copy(update={'target':'other-control'})
    with pytest.raises(PermissionError): service.consume_browser_action(receipt,changed)
    from asset_based_agent.technical_platform.permissions import PermissionService
    from asset_based_agent.technical_platform.store import PlatformStore
    other=PermissionService(PlatformStore(store.path,'bob',create=False))
    with pytest.raises(PermissionError): other.consume_browser_action(receipt,request)
    service.revoke(run)
    with pytest.raises(PermissionError): service.consume_browser_action(receipt,request)


def test_concurrent_consume_has_one_winner(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    _, _, service, request=ready(tmp_path)
    receipt=service.authorize_browser_action(request,confirmed=True)
    def consume(_):
        try: service.consume_browser_action(receipt,request); return True
        except PermissionError: return False
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sum(pool.map(consume,range(2)))==1


def test_v6_upgrade_adds_empty_receipts_preserving_backup(tmp_path):
    import sqlite3

    from asset_based_agent.technical_platform.local_migrations import migrate_database
    path=tmp_path/'legacy.sqlite'
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE sample(value TEXT)'); db.execute("INSERT INTO sample VALUES('keep')")
        db.execute('PRAGMA user_version=6')
    backup=migrate_database(path)
    assert backup is not None
    with sqlite3.connect(backup) as db: assert db.execute('PRAGMA user_version').fetchone()[0]==6
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT value FROM sample').fetchone()[0]=='keep'
        assert db.execute('SELECT count(*) FROM browser_action_authorizations').fetchone()[0]==0


def test_expired_receipt_and_finished_step_cannot_dispatch(tmp_path):
    store, run, service, request=ready(tmp_path)
    receipt=service.authorize_browser_action(request,confirmed=True)
    with store.connect() as db:
        db.execute('UPDATE browser_action_authorizations SET expires_at=0 WHERE id=?',(receipt,))
    with pytest.raises(PermissionError): service.consume_browser_action(receipt,request)
    with pytest.raises(PermissionError): service.authorize_browser_action(request,confirmed=True)
    fresh=request.model_copy(update={'target':'new-observation:control-1'})
    receipt=service.authorize_browser_action(fresh,confirmed=True)
    with store.connect() as db:
        db.execute("UPDATE execution_steps SET state='succeeded' WHERE run=?",(run,))
    with pytest.raises(PermissionError): service.consume_browser_action(receipt,fresh)


def test_v7_failure_rolls_back_without_changing_v6_rows(tmp_path,monkeypatch):
    import sqlite3

    from asset_based_agent.technical_platform import local_migrations as migrations
    path=tmp_path/'v6.sqlite'
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE sample(value TEXT)'); db.execute("INSERT INTO sample VALUES('keep')")
        db.execute('PRAGMA user_version=6')
    def fail(db):
        db.execute('CREATE TABLE partial_v7(id INTEGER)')
        raise RuntimeError('synthetic migration failure')
    monkeypatch.setattr(migrations,'apply_v7',fail)
    with pytest.raises(RuntimeError): migrations.migrate_database(path)
    with sqlite3.connect(path) as db:
        assert db.execute('PRAGMA user_version').fetchone()[0]==6
        assert db.execute('SELECT value FROM sample').fetchone()[0]=='keep'
        assert db.execute("SELECT name FROM sqlite_master WHERE name='partial_v7'").fetchone() is None


def test_changed_execution_claim_invalidates_pending_browser_consent(tmp_path):
    store, run, service, request=ready(tmp_path)
    receipt=service.authorize_browser_action(request,confirmed=True)
    with store.connect() as db:
        db.execute("UPDATE execution_steps SET claim_token='another-executor' WHERE run=?",(run,))
    with pytest.raises(PermissionError): service.consume_browser_action(receipt,request)
