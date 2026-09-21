from datetime import datetime, timezone

NOW = datetime(2026, 9, 17, 12, tzinfo=timezone.utc)


def test_context_uses_versioned_layered_memories_without_cross_session_pollution(
    tmp_path,
):
    from asset_based_agent.technical_platform.context import build_context
    from asset_based_agent.technical_platform.memory_service import MemoryService
    from asset_based_agent.technical_platform.store import PlatformStore

    store = PlatformStore(tmp_path / "state.sqlite", "alice")
    project = store.create_project("one")
    session = store.create_session(project)
    other_session = store.create_session(project)
    service = MemoryService(store, clock=lambda: NOW)
    project_id = service.create(
        scope="project",
        project_id=project,
        key="format",
        text="Project format",
        confirmed=True,
    )
    service.create(
        scope="session",
        project_id=project,
        session_id=other_session,
        key="secret",
        text="Other session only",
        confirmed=True,
    )
    context = build_context(store, session, "current", clock=lambda: NOW)
    assert context["memory_ids"] == [project_id]
    assert context["memories"][0]["scope"] == "project"
    assert context["memories"][0]["source"] == "explicit_user"
    assert len(context["memories"][0]["version"]) == 64
    assert "Other session only" not in str(context)


def test_retrieval_budget_does_not_truncate_memory_or_current_request(tmp_path):
    from asset_based_agent.technical_platform.context import (
        build_context,
        model_request,
    )
    from asset_based_agent.technical_platform.memory_service import MemoryService
    from asset_based_agent.technical_platform.store import PlatformStore

    store = PlatformStore(tmp_path / "state.sqlite", "alice")
    project = store.create_project("one")
    session = store.create_session(project)
    service = MemoryService(store, clock=lambda: NOW)
    for index in range(8):
        service.create(
            scope="project",
            project_id=project,
            key=f"key-{index}",
            text=(str(index) * 600),
            priority=index,
            confirmed=True,
        )
    current = "x" * 9000
    context = build_context(store, session, current, clock=lambda: NOW)
    rendered = model_request(current, context)
    assert rendered.endswith(current)
    assert len(rendered) <= 12000
    assert all(len(item["text"]) == 600 for item in context["memories"])
