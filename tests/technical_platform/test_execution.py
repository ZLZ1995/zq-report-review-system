import json
import threading

import pytest
from openpyxl import Workbook

from asset_based_agent.technical_platform.execution import execute_task
from asset_based_agent.technical_platform.skills import PREFLIGHT, REVIEW, digest
from asset_based_agent.technical_platform.store import PlatformStore
from asset_based_agent.technical_platform.task_spec import build_task_spec


def make_run(tmp_path, remote=False, change=None, *, authorize=True):
    store = PlatformStore(tmp_path / "db.sqlite", "alice")
    project = store.create_project("one")
    session = store.create_session(project)
    path = tmp_path / "data.xlsx"
    book = Workbook()
    book.active["A1"] = "visible evidence"
    book.create_sheet("secret").sheet_state = "hidden"
    book["secret"]["A1"] = "DO_NOT_UPLOAD"
    book.save(path)
    store.add_file(project, path, digest(path))
    snapshot = build_task_spec(store, session, "CURRENT", REVIEW if remote else PREFLIGHT,
                               store.files(project), model="test" if remote else None,
                               instructions="rules" if remote else "").to_snapshot()
    if change:
        change(snapshot)
    run = store.start_run(session, snapshot)
    if authorize and snapshot['schema_version'] == 2 and snapshot['permissions']['modify_originals'] is False:
        from asset_based_agent.technical_platform.permissions import PermissionService
        PermissionService(store).authorize(run, snapshot, confirmed=True)
    return store, run, project


def test_execution_enforces_readonly_before_reading(tmp_path):
    store, run, _ = make_run(tmp_path, change=lambda s: s["permissions"].update(modify_originals=True))
    with pytest.raises(PermissionError):
        execute_task(store, run, threading.Event(), lambda _: None)
    assert store.run(run)["state"] == "failed"
    with store.connect() as db:
        assert "planning" in db.execute("SELECT detail FROM events WHERE run=?", (run,)).fetchone()[0]


def test_execution_rejects_malformed_request_identity(tmp_path):
    store, run, _ = make_run(tmp_path, change=lambda s: s.update(request_id=''))
    with pytest.raises(ValueError):
        execute_task(store, run, threading.Event(), lambda _: None)
    assert store.run(run)['state'] == 'failed'


def test_execution_rejects_changed_plan_before_tools(tmp_path, monkeypatch):
    from asset_based_agent.technical_platform import execution
    def change(snapshot):
        snapshot['execution_plan'] = {'identity': 'forged', 'steps': []}
    store, run, _ = make_run(tmp_path, change=change)
    def never(*args, **kwargs):
        pytest.fail('Invalid plan reached execution')
    monkeypatch.setattr(execution, 'preflight', never)
    with pytest.raises((ValueError, PermissionError)):
        execute_task(store, run, threading.Event(), lambda _: None)
    assert store.run(run)['state'] == 'failed'


def test_valid_shaped_plan_with_different_rules_is_not_executed(tmp_path, monkeypatch):
    from asset_based_agent.technical_platform import execution
    def change(snapshot):
        snapshot['execution_plan']['steps'][0]['rules_sha256'] = '0' * 64
    store, run, _ = make_run(tmp_path, change=change)
    def never(*args, **kwargs):
        pytest.fail('Changed rules must not execute')
    monkeypatch.setattr(execution, 'preflight', never)
    with pytest.raises(PermissionError, match='计划'):
        execute_task(store, run, threading.Event(), lambda _: None)


@pytest.mark.parametrize('change', [
    lambda scope: scope.update(session_id='other-session'),
    lambda scope: scope.update(excluded=scope['targets']),
    lambda scope: scope.update(targets=[]),
    lambda scope: scope.update(revision=True),
])
def test_execution_rejects_changed_scope_before_reading(tmp_path, monkeypatch, change):
    from asset_based_agent.technical_platform import execution
    store, run, _ = make_run(tmp_path, change=lambda s: change(s['file_scope']))
    def never(*args, **kwargs):
        pytest.fail('scope mismatch must not reach file extraction')
    monkeypatch.setattr(execution, 'preflight', never)
    with pytest.raises(PermissionError):
        execute_task(store, run, threading.Event(), lambda _: None)
    assert store.run(run)['state'] == 'failed'


def test_external_skill_must_be_installed_before_execution(tmp_path):
    store, run, _ = make_run(tmp_path, change=lambda s: s.update(external_skill={
        'id': 'not-installed', 'version': '1.0.0', 'sha256': 'fake'}))
    with pytest.raises(PermissionError):
        execute_task(store, run, threading.Event(), lambda _: None)
    assert store.run(run)['state'] == 'failed'


def test_execution_refreshes_memory_and_preserves_filtered_review(tmp_path):
    store, run, project = make_run(tmp_path, remote=True)
    keep = store.remember(project, "KEEP_PREFERENCE", confirmed=True)
    deleted = store.remember(project, "REMOVED_PREFERENCE", confirmed=True)
    store.forget(project, deleted)

    class Provider:
        model_id = "test"
        skill_instructions = "rules"

        def set_client_job_id(self, key):
            assert key == f"PLATFORM-{run}-execute"

        def review_batches(self, batches, progress_callback=None):
            with pytest.raises(ValueError):
                execute_task(store, run, threading.Event(), lambda _: None, provider=self)
            assert store.run(run)["state"] == "running"
            assert "KEEP_PREFERENCE" in self.user_request
            assert "REMOVED_PREFERENCE" not in self.user_request
            assert self.user_request.endswith("CURRENT")
            assert "DO_NOT_UPLOAD" not in str(batches)
            return []

    result = execute_task(store, run, threading.Event(), lambda _: None, provider=Provider())
    assert result["kind"] == "review"
    assert store.run(run)["state"] == "succeeded"
    with store.connect() as db:
        assert db.execute('SELECT state FROM execution_steps WHERE run=?', (run,)).fetchone()[0] == 'succeeded'
        assert [r[0] for r in db.execute('SELECT kind FROM execution_events WHERE run=? ORDER BY sequence', (run,))] == ['running', 'succeeded']
    assert json.loads(store.run(run)["snapshot"])["execution_context"]["memory_ids"] == [keep]
    with store.connect() as db:
        assert db.execute('SELECT COUNT(*) FROM execution_results WHERE run=?', (run,)).fetchone()[0] == 1


def test_cancel_and_legacy_do_not_call_model(tmp_path):
    store, run, project = make_run(tmp_path)
    cancel = threading.Event()
    cancel.set()
    assert execute_task(store, run, cancel, lambda _: None)["kind"] == "cancelled"
    session = store.sessions(project)[0]["id"]
    legacy = store.start_run(session, {"files": store.files(project)})
    with pytest.raises(PermissionError):
        execute_task(store, legacy, threading.Event(), lambda _: None)
    assert store.run(legacy)["state"] == "failed"


def test_changed_attachment_fails_validation_without_model(tmp_path):
    store, run, project = make_run(tmp_path)
    from pathlib import Path

    Path(store.files(project)[0]["path"]).write_bytes(b"changed")
    with pytest.raises(ValueError, match="文件已变化"):
        execute_task(store, run, threading.Event(), lambda _: None)
    assert store.run(run)["state"] == "failed"


def test_model_mismatch_is_blocked_before_execution(tmp_path):
    store, run, _ = make_run(tmp_path, remote=True)

    class Provider:
        model_id = "wrong"
        skill_instructions = "rules"

    with pytest.raises(PermissionError, match="模型或规则"):
        execute_task(store, run, threading.Event(), lambda _: None, provider=Provider())
    assert store.run(run)["state"] == "failed"


def test_post_execution_hash_gate_records_validation_failure(tmp_path):
    from pathlib import Path

    store, run, project = make_run(tmp_path, remote=True)

    class Provider:
        model_id = "test"
        skill_instructions = "rules"

        def set_client_job_id(self, key):
            pass

        def review_batches(self, batches, progress_callback=None):
            # Deliberately tamper with a synthetic attachment, never a formal document.
            Path(store.files(project)[0]["path"]).write_bytes(b"changed")
            return []

    with pytest.raises(ValueError, match="原文件发生变化"):
        execute_task(store, run, threading.Event(), lambda _: None, provider=Provider())
    assert store.run(run)["state"] == "failed"
    with store.connect() as db:
        details = [row[0] for row in db.execute("SELECT detail FROM events WHERE run=?", (run,))]
    assert "validation: SourceValidationError" in details


def test_other_account_cannot_execute_run(tmp_path):
    store, run, _ = make_run(tmp_path)
    other = PlatformStore(store.path, "bob")
    with pytest.raises(PermissionError):
        execute_task(other, run, threading.Event(), lambda _: None)
    assert store.run(run)["state"] == "queued"


def test_v1_task_cannot_execute_even_with_matching_snapshot(tmp_path, monkeypatch):
    from asset_based_agent.technical_platform import execution
    store, run, _ = make_run(tmp_path, change=lambda s: s.update(schema_version=1))
    monkeypatch.setattr(execution, 'preflight', lambda *a, **k: pytest.fail('legacy task executed'))
    with pytest.raises(PermissionError):
        execute_task(store, run, threading.Event(), lambda _: None)


@pytest.mark.parametrize('field', ['execution_plan', 'file_scope'])
def test_v2_missing_required_scope_or_plan_cannot_reach_tool(tmp_path, monkeypatch, field):
    from asset_based_agent.technical_platform import execution
    store, run, _ = make_run(tmp_path, change=lambda s: s.pop(field))
    monkeypatch.setattr(execution, 'preflight', lambda *a, **k: pytest.fail('incomplete v2 task executed'))
    with pytest.raises(PermissionError):
        execute_task(store, run, threading.Event(), lambda _: None)


@pytest.mark.parametrize('outcome', ['failed', 'cancelled', 'interrupted'])
def test_step_records_failure_and_cancel_but_never_replays_interrupted_call(tmp_path, monkeypatch, outcome):
    from asset_based_agent.report_review_app.services.task_cancellation import (
        TaskCancelled,
    )
    from asset_based_agent.technical_platform import execution
    from asset_based_agent.technical_platform.event_store import ExecutionStore

    store, run, _ = make_run(tmp_path)
    calls = []
    def interrupted(*args, **kwargs):
        calls.append(run)
        if outcome == 'cancelled':
            raise TaskCancelled('synthetic cancellation')
        if outcome == 'failed':
            raise ValueError('synthetic failure')
        raise SystemExit('synthetic process interruption')
    monkeypatch.setattr(execution, 'preflight', interrupted)
    if outcome == 'cancelled':
        assert execute_task(store, run, threading.Event(), lambda _: None)['kind'] == 'cancelled'
    else:
        with pytest.raises(ValueError if outcome == 'failed' else SystemExit):
            execute_task(store, run, threading.Event(), lambda _: None)
    reopened = PlatformStore(store.path, 'alice', create=False)
    expected = 'running' if outcome == 'interrupted' else outcome
    with reopened.connect() as db:
        assert db.execute('SELECT state FROM execution_steps WHERE run=?', (run,)).fetchone()[0] == expected
    kinds = [event['kind'] for event in ExecutionStore(reopened).events(run)]
    assert kinds == (['running'] if outcome == 'interrupted' else ['running', outcome])
    with pytest.raises(ValueError):
        execute_task(reopened, run, threading.Event(), lambda _: None)
    assert calls == [run]


@pytest.mark.parametrize('error', [TimeoutError, ConnectionError])
def test_uncertain_review_cannot_report_success_or_repeat_call(tmp_path, error):
    store, run, _ = make_run(tmp_path, remote=True)
    calls = []
    class Provider:
        model_id = 'test'
        skill_instructions = 'rules'
        def set_client_job_id(self, identity):
            assert identity == f'PLATFORM-{run}-execute'
        def review_batches(self, batches, progress_callback=None):
            calls.append(run)
            raise error('synthetic-secret-not-for-log')
    with pytest.raises(error):
        execute_task(store, run, threading.Event(), lambda _: None, provider=Provider())
    assert store.run(run)['state'] == 'interrupted'
    assert store.run(run)['result'] is None
    with store.connect() as db:
        assert db.execute('SELECT state FROM execution_steps WHERE run=?', (run,)).fetchone()[0] == 'unknown'
        assert 'synthetic-secret' not in str([tuple(r) for r in db.execute('SELECT * FROM events')])
    with pytest.raises(ValueError):
        execute_task(store, run, threading.Event(), lambda _: None, provider=Provider())
    assert calls == [run]
