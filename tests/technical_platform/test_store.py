import sqlite3

import pytest

from asset_based_agent.technical_platform.skills import (
    PREFLIGHT,
    SkillRegistry,
    SkillSpec,
)
from asset_based_agent.technical_platform.store import PlatformStore


def test_projects_sessions_and_messages_survive_restart(tmp_path):
    path = tmp_path / "platform.sqlite"
    store = PlatformStore(path, "alice")
    project = store.create_project("设备项目")
    session = store.create_session(project)
    store.append(session, "user", "审核资料")
    reopened = PlatformStore(path, "alice")
    assert reopened.messages(session)[0]["text"] == "审核资料"
    other = PlatformStore(path, "bob")
    assert other.projects() == []
    with pytest.raises(PermissionError):
        other.append(session, "user", "cross-user injection")


def test_missing_database_after_open_is_not_silently_recreated(tmp_path):
    path = tmp_path / 'disconnected.sqlite'
    store = PlatformStore(path, 'alice')
    store.create_project('synthetic')
    moved = path.with_suffix('.saved')
    path.rename(moved)
    with pytest.raises(sqlite3.OperationalError):
        store.projects()
    assert not path.exists()
    assert moved.is_file()


def test_memory_explicit_project_scoped_and_deletable(tmp_path):
    store = PlatformStore(tmp_path / "p.sqlite", "alice")
    a, b = store.create_project("A"), store.create_project("B")
    with pytest.raises(ValueError):
        store.remember(a, "猜测", confirmed=False)
    identity = store.remember(a, "输出简洁", confirmed=True)
    assert store.memories(b) == []
    store.forget(a, identity)
    assert store.memories(a) == []


def test_runs_terminal_state_and_feedback_boundaries(tmp_path):
    store = PlatformStore(tmp_path / "p.sqlite", "alice")
    session = store.create_session(store.create_project("A"))
    run = store.start_run(session, {"skill": PREFLIGHT.id})
    store.transition(run, "running", "start")
    store.transition(run, "validating", "check")
    store.transition(run, "succeeded", "done")
    with pytest.raises(ValueError):
        store.transition(run, "running", "restart")
    with pytest.raises(ValueError):
        store.feedback(run, "ignore", "ignored")
    with pytest.raises(PermissionError):
        PlatformStore(tmp_path / "p.sqlite", "bob").run(run)


def test_skill_registry_rejects_write_permission():
    registry = SkillRegistry()
    registry.register(PREFLIGHT)
    with pytest.raises(PermissionError):
        registry.register(
            SkillSpec("edit", "1", "write", frozenset({"write_original"}))
        )


def test_explicit_legacy_claim_preserves_history_and_cannot_take_other_accounts(tmp_path):
    path = tmp_path / "state.sqlite"
    legacy = PlatformStore(path, "local-preview")
    project = legacy.create_project("旧项目")
    session = legacy.create_session(project)
    legacy.append(session, "user", "旧会话")
    legacy.remember(project, "偏好", confirmed=True)
    target = PlatformStore(path, "alice")
    assert target.projects() == []
    assert target.legacy_projects()[0]["id"] == project
    with pytest.raises(ValueError):
        target.claim_legacy_project(project, confirmed=False)
    target.claim_legacy_project(project, confirmed=True)
    assert target.messages(session)[0]["text"] == "旧会话"
    assert target.memories(project)[0]["text"] == "偏好"
    assert legacy.projects() == []
    with target.connect() as db:
        assert db.execute("SELECT previous_owner FROM project_claims").fetchone()[0] == "local-preview"
    with pytest.raises(PermissionError):
        PlatformStore(path, "bob").claim_legacy_project(project, confirmed=True)


def test_legacy_claim_rejects_offline_and_active_projects(tmp_path):
    path = tmp_path / "state.sqlite"
    legacy = PlatformStore(path, "local-preview")
    project = legacy.create_project("运行中")
    legacy.start_run(legacy.create_session(project), {})
    with pytest.raises(PermissionError):
        PlatformStore(path, "offline-local").claim_legacy_project(project, confirmed=True)
    with pytest.raises(ValueError, match="任务"):
        PlatformStore(path, "alice").claim_legacy_project(project, confirmed=True)
    assert legacy.project(project)
