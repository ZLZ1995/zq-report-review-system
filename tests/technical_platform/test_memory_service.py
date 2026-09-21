from datetime import datetime, timedelta, timezone

import pytest


def utc(hour=12):
    return datetime(2026, 9, 17, hour, tzinfo=timezone.utc)


def test_memory_requires_confirmation_and_is_owner_scoped(tmp_path):
    from asset_based_agent.technical_platform.memory_service import MemoryService
    from asset_based_agent.technical_platform.store import PlatformStore

    path = tmp_path / "state.sqlite"
    alice = PlatformStore(path, "alice")
    project = alice.create_project("one")
    service = MemoryService(alice, clock=utc)
    with pytest.raises(ValueError, match="confirm"):
        service.create(
            scope="project",
            project_id=project,
            key="output.unit",
            text="Display amounts in ten-thousands",
            confirmed=False,
        )
    identity = service.create(
        scope="project",
        project_id=project,
        key="output.unit",
        text="Display amounts in ten-thousands",
        confirmed=True,
    )
    assert service.get(identity).text == "Display amounts in ten-thousands"
    with pytest.raises(PermissionError):
        MemoryService(PlatformStore(path, "bob"), clock=utc).get(identity)


def test_memory_revoke_is_immediate_but_snapshot_identity_remains_traceable(tmp_path):
    from asset_based_agent.technical_platform.memory_retrieval import retrieve_memories
    from asset_based_agent.technical_platform.memory_service import MemoryService
    from asset_based_agent.technical_platform.store import PlatformStore

    store = PlatformStore(tmp_path / "state.sqlite", "alice")
    project = store.create_project("one")
    session = store.create_session(project)
    service = MemoryService(store, clock=utc)
    identity = service.create(
        scope="project",
        project_id=project,
        key="tone",
        text="Use concise wording",
        confirmed=True,
    )
    before = retrieve_memories(store, session, clock=utc)
    assert [item.id for item in before] == [identity]
    snapshot_ids = [item.id for item in before]
    service.revoke(identity)
    assert retrieve_memories(store, session, clock=utc) == []
    assert snapshot_ids == [identity]
    assert service.get(identity).status == "revoked"


def test_scope_priority_conflict_and_expiry_are_deterministic(tmp_path):
    from asset_based_agent.technical_platform.memory_retrieval import retrieve_memories
    from asset_based_agent.technical_platform.memory_service import MemoryService
    from asset_based_agent.technical_platform.store import PlatformStore

    store = PlatformStore(tmp_path / "state.sqlite", "alice")
    project = store.create_project("one")
    other_project = store.create_project("two")
    session = store.create_session(project)
    service = MemoryService(store, clock=utc)
    user = service.create(scope="user", key="tone", text="User default", confirmed=True)
    project_memory = service.create(
        scope="project",
        project_id=project,
        key="tone",
        text="Project default",
        confirmed=True,
    )
    session_memory = service.create(
        scope="session",
        project_id=project,
        session_id=session,
        key="tone",
        text="Session override",
        confirmed=True,
    )
    service.create(
        scope="project",
        project_id=other_project,
        key="other",
        text="Never leak",
        confirmed=True,
    )
    service.create(
        scope="project",
        project_id=project,
        key="expired",
        text="Old value",
        expires_at=utc() - timedelta(seconds=1),
        confirmed=True,
    )
    selected = retrieve_memories(store, session, clock=utc)
    assert [(item.key, item.text) for item in selected] == [
        ("tone", "Session override")
    ]
    assert session_memory in {item.id for item in selected}
    assert user not in {item.id for item in selected}
    assert project_memory not in {item.id for item in selected}
