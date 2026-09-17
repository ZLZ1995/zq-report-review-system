import json

import pytest

from asset_based_agent.technical_platform.session_service import SessionService
from asset_based_agent.technical_platform.store import PlatformStore


def test_descendant_inherits_frozen_ancestor_not_later_results(tmp_path):
    store = PlatformStore(tmp_path / 'state.sqlite', 'alice')
    project = store.create_project('p')
    parent = store.create_session(project)
    original = completed(store, parent, {'kind': 'preflight', 'summary': 'original'})
    store.append(parent, 'assistant', 'anchor')
    service = SessionService(store)
    child = service.fork(parent, store.messages(parent)[0]['id'], 'child')
    completed(store, parent, {'kind': 'preflight', 'summary': 'later parent task'})
    child_run = completed(store, child, {'kind': 'preflight', 'summary': 'child fact'})
    store.append(child, 'assistant', 'child anchor')
    grandchild = service.fork(child, store.messages(child)[0]['id'], 'grandchild')
    assert [r['run_id'] for r in service.branch_results(grandchild)] == [original, child_run]
    assert store.runs(grandchild) == []
    with store.connect() as db:
        assert db.execute('SELECT COUNT(*) FROM execution_authorizations').fetchone()[0] == 0
    with store.connect() as db:
        row = db.execute('SELECT context_snapshot FROM session_metadata WHERE session=?', (child,)).fetchone()
        changed = json.loads(row[0])
        changed['completed_facts'] = []
        db.execute('UPDATE session_metadata SET context_snapshot=? WHERE session=?',
                   (json.dumps(changed), child))
    with pytest.raises(ValueError, match='ancestor'):
        service.branch_results(grandchild)


def completed(store, session, result):
    run = store.start_run(session, {})
    store.claim_run(run)
    store.save_result(run, result)
    store.transition(run, 'validating', 'checked')
    store.transition(run, 'succeeded', 'done')
    return run


def test_excessive_branch_depth_rejected_without_partial_child(tmp_path):
    store = PlatformStore(tmp_path / 'state.sqlite', 'alice')
    project = store.create_project('p')
    parent = store.create_session(project)
    service = SessionService(store)
    rejected = False
    for _ in range(40):
        store.append(parent, 'user', 'anchor')
        count = len(service.list(project))
        try:
            parent = service.fork(parent, store.messages(parent)[-1]['id'], 'child')
        except ValueError as exc:
            assert 'depth' in str(exc)
            assert len(service.list(project)) == count
            rejected = True
            break
    assert rejected


def test_duplicate_branch_reference_rejected(tmp_path):
    store = PlatformStore(tmp_path / 'state.sqlite', 'alice')
    project = store.create_project('p')
    parent = store.create_session(project)
    completed(store, parent, {'kind': 'preflight'})
    store.append(parent, 'user', 'anchor')
    service = SessionService(store)
    child = service.fork(parent, store.messages(parent)[0]['id'], 'child')
    with store.connect() as db:
        snapshot = json.loads(db.execute('SELECT context_snapshot FROM session_metadata WHERE session=?',
                                        (child,)).fetchone()[0])
        snapshot['completed_facts'] *= 2
        db.execute('UPDATE session_metadata SET context_snapshot=? WHERE session=?', (json.dumps(snapshot), child))
    with pytest.raises(ValueError, match='reference'):
        service.branch_results(child)


def test_branch_freezes_completed_result_references_at_anchor(tmp_path):
    store = PlatformStore(tmp_path / 'state.sqlite', 'alice')
    project = store.create_project('p')
    parent = store.create_session(project)
    result = {'kind': 'preflight', 'documents': [], 'summary': 'synthetic fact'}
    run = completed(store, parent, result)
    store.append(parent, 'assistant', 'completed result')
    anchor = store.messages(parent)[0]['id']
    later = completed(store, parent, {'kind': 'preflight', 'summary': 'later'})
    pending = store.start_run(parent, {})
    service = SessionService(store)
    child = service.fork(parent, anchor, 'child')
    snapshot = json.loads(next(r for r in service.list(project) if r['id'] == child)['context_snapshot'])
    assert [r['run_id'] for r in snapshot['completed_facts']] == [run]
    assert 'synthetic fact' not in json.dumps(snapshot)
    assert later not in json.dumps(snapshot) and pending not in json.dumps(snapshot)
    assert service.branch_results(child) == [{'run_id': run, 'result': result}]
    assert not store.runs(child)
    store.save_result(run, {'kind': 'preflight', 'summary': 'changed'})
    with pytest.raises(ValueError, match='changed'):
        service.branch_results(child)


def test_branch_result_access_rejects_other_account_and_changed_anchor(tmp_path):
    store = PlatformStore(tmp_path / 'state.sqlite', 'alice')
    project = store.create_project('p')
    parent = store.create_session(project)
    completed(store, parent, {'kind': 'preflight'})
    store.append(parent, 'assistant', 'anchor')
    anchor = store.messages(parent)[0]['id']
    service = SessionService(store)
    child = service.fork(parent, anchor, 'child')
    with pytest.raises(PermissionError):
        SessionService(PlatformStore(store.path, 'bob')).branch_results(child)
    with store.connect() as db:
        db.execute('UPDATE messages SET text=? WHERE id=?', ('changed', anchor))
    with pytest.raises(ValueError, match='anchor'):
        service.branch_results(child)


@pytest.mark.parametrize('change', ['replace', 'delete', 'outside'])
def test_generated_branch_artifact_must_retain_version_and_scope(tmp_path, change):
    from asset_based_agent.technical_platform.skills import digest
    store = PlatformStore(tmp_path / 'state.sqlite', 'alice')
    project = store.create_project('p')
    parent = store.create_session(project)
    run = store.start_run(parent, {})
    store.claim_run(run)
    root = tmp_path / 'runs' / run / 'output'
    root.mkdir(parents=True)
    path = (tmp_path if change == 'outside' else root) / 'synthetic.md'
    path.write_text('synthetic result', encoding='utf-8')
    store.save_result(run, {'kind': 'generation', 'ok': True, 'artifacts': [
        {'path': str(path), 'name': path.name, 'sha256': digest(path)}]})
    store.transition(run, 'validating', 'checked')
    store.transition(run, 'succeeded', 'done')
    store.append(parent, 'assistant', 'done')
    service = SessionService(store)
    child = service.fork(parent, store.messages(parent)[0]['id'], 'child')
    if change != 'outside':
        assert len(service.branch_results(child)) == 1
    if change == 'replace':
        path.write_text('changed', encoding='utf-8')
    elif change == 'delete':
        path.unlink()
    with pytest.raises((ValueError, PermissionError)):
        service.branch_results(child)


def test_real_compound_branch_checks_step_artifact(tmp_path):
    import threading

    from test_compound_task import prepared

    from asset_based_agent.technical_platform.execution import execute_task
    from asset_based_agent.technical_platform.permissions import PermissionService
    from asset_based_agent.technical_platform.plan_results import step_artifact_path
    store, parent, snapshot = prepared(tmp_path)
    run = store.start_run(parent, snapshot)
    PermissionService(store).authorize(run, snapshot, confirmed=True)
    execute_task(store, run, threading.Event(), lambda _: None)
    store.append(parent, 'assistant', 'done')
    service = SessionService(store)
    child = service.fork(parent, store.messages(parent)[-1]['id'], 'child')
    assert len(service.branch_results(child)) == 1
    path = step_artifact_path(store, parent, run, 0, 0)
    path.write_bytes(b'synthetic replacement')
    with pytest.raises(ValueError):
        service.branch_results(child)
