import json
import threading

import pytest
from openpyxl import Workbook

from asset_based_agent.technical_platform.execution import execute_task
from asset_based_agent.technical_platform.skills import PREFLIGHT, REVIEW, digest
from asset_based_agent.technical_platform.store import PlatformStore
from asset_based_agent.technical_platform.task_spec import build_task_spec


def make_run(tmp_path, remote=False, change=None):
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
    return store, store.start_run(session, snapshot), project


def test_execution_enforces_readonly_before_reading(tmp_path):
    store, run, _ = make_run(tmp_path, change=lambda s: s["permissions"].update(modify_originals=True))
    with pytest.raises(PermissionError):
        execute_task(store, run, threading.Event(), lambda _: None)
    assert store.run(run)["state"] == "failed"
    with store.connect() as db:
        assert "planning" in db.execute("SELECT detail FROM events WHERE run=?", (run,)).fetchone()[0]


def test_execution_refreshes_memory_and_preserves_filtered_review(tmp_path):
    store, run, project = make_run(tmp_path, remote=True)
    keep = store.remember(project, "KEEP_PREFERENCE", confirmed=True)
    deleted = store.remember(project, "REMOVED_PREFERENCE", confirmed=True)
    store.forget(project, deleted)

    class Provider:
        model_id = "test"
        skill_instructions = "rules"

        def set_client_job_id(self, key):
            assert key == f"PLATFORM-{run}"

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
    assert json.loads(store.run(run)["snapshot"])["execution_context"]["memory_ids"] == [keep]


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
    assert "validation: ValueError" in details


def test_other_account_cannot_execute_run(tmp_path):
    store, run, _ = make_run(tmp_path)
    other = PlatformStore(store.path, "bob")
    with pytest.raises(PermissionError):
        execute_task(other, run, threading.Event(), lambda _: None)
    assert store.run(run)["state"] == "queued"
