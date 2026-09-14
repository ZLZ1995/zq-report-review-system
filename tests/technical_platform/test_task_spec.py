import pytest

from asset_based_agent.technical_platform.skills import PREFLIGHT, REVIEW, digest
from asset_based_agent.technical_platform.store import PlatformStore
from asset_based_agent.technical_platform.task_spec import (
    build_task_spec,
    read_snapshot,
)


def setup_task(tmp_path):
    store = PlatformStore(tmp_path / "tasks.sqlite", "alice")
    project = store.create_project("A")
    session = store.create_session(project)
    path = tmp_path / "sample.txt"
    path.write_text("sample", encoding="utf-8")
    store.add_file(project, path, digest(path))
    return store, project, session


def test_spec_captures_scope_versions_and_explicit_readonly_permissions(tmp_path):
    store, project, session = setup_task(tmp_path)
    spec = build_task_spec(store, session, "check totals", PREFLIGHT,
                           store.files(project), model=None, instructions="")
    snapshot = spec.to_snapshot()
    assert snapshot["schema_version"] == 1
    assert snapshot["owner"] == "alice"
    assert snapshot["project_id"] == project
    assert snapshot["session_id"] == session
    assert snapshot["user_request"] == "check totals"
    assert snapshot["permissions"]["modify_originals"] is False
    assert snapshot["permissions"]["call_model"] is False
    assert snapshot["selected_files"][0]["version"] == store.files(project)[0]["sha256"]
    assert "original_hash_unchanged" in snapshot["acceptance_gates"]
    assert len(snapshot["skill_rules_sha256"]) == 64
    run = store.start_run(session, snapshot)
    assert run == snapshot["task_id"]


def test_spec_rejects_cross_scope_or_tampered_files(tmp_path):
    store, project, session = setup_task(tmp_path)
    files = store.files(project)
    files[0]["path"] = "arbitrary-path"
    with pytest.raises(PermissionError):
        build_task_spec(store, session, "review", PREFLIGHT, files)
    other = PlatformStore(store.path, "bob")
    with pytest.raises(PermissionError):
        build_task_spec(other, session, "review", PREFLIGHT, [])


def test_remote_spec_requires_model_and_rules(tmp_path):
    store, project, session = setup_task(tmp_path)
    with pytest.raises(ValueError):
        build_task_spec(store, session, "review", REVIEW, store.files(project))


def test_legacy_snapshot_is_readable_but_not_replay_authorization():
    legacy = read_snapshot({"files": [], "capabilities": ["modify_originals"]})
    assert legacy["schema_version"] == 0
    assert legacy["requires_confirmation"] is True
    assert legacy["permissions"] == {}
    with pytest.raises(ValueError):
        read_snapshot({"schema_version": 999})
