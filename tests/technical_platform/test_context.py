from asset_based_agent.technical_platform.context import build_context, model_request
from asset_based_agent.technical_platform.store import PlatformStore


def test_context_scoped_confirmed_retractable_and_bounded(tmp_path):
    store = PlatformStore(tmp_path / "db.sqlite", "alice")
    project = store.create_project("one")
    session = store.create_session(project)
    other = store.create_project("two")
    store.remember(other, "OTHER_PROJECT", confirmed=True)
    other_session = store.create_session(project)
    store.append(other_session, "user", "OTHER_SESSION")
    memory = store.remember(project, "prefer concise output", confirmed=True)
    store.append(session, "assistant", "UNVERIFIED_OLD_ISSUE")
    for _ in range(20):
        store.append(session, "user", "prior request " * 500)
    context = build_context(store, session, "current")
    assert context["memory_ids"] == [memory]
    assert len(context["history"]) <= 6
    text = model_request("current", context)
    assert "OTHER_PROJECT" not in text and "OTHER_SESSION" not in text
    assert "UNVERIFIED_OLD_ISSUE" not in text
    assert "prefer concise output" in text
    assert len(text) < 10000
    assert text.endswith("current")
    store.forget(project, memory)
    assert build_context(store, session, "current")["memories"] == []


def test_current_request_not_duplicated_and_plain_request_preserved(tmp_path):
    store = PlatformStore(tmp_path / "db.sqlite", "alice")
    session = store.create_session(store.create_project("one"))
    store.append(session, "user", "current")
    context = build_context(store, session, "current")
    assert context["history"] == []
    assert model_request("current", context) == "current"


def test_memory_revision_is_content_hash_and_local_preflight_does_not_upload(tmp_path):
    store = PlatformStore(tmp_path / "db.sqlite", "alice")
    project = store.create_project("one")
    session = store.create_session(project)
    store.remember(project, "do not change originals", confirmed=True)
    context = build_context(store, session, "review")
    assert len(context["memories"][0]["version"]) == 64
    assert context["prior_results_available"] is False


def test_wire_budget_preserves_current_request_without_truncation(tmp_path):
    store = PlatformStore(tmp_path / "db.sqlite", "alice")
    project = store.create_project("one")
    session = store.create_session(project)
    store.remember(project, "preference" * 100, confirmed=True)
    current = "x" * 11999
    context = build_context(store, session, current)
    assert context["memory_ids"] == []
    assert model_request(current, context) == current


def test_similar_long_requests_do_not_erase_previous_history(tmp_path):
    store = PlatformStore(tmp_path / "db.sqlite", "alice")
    session = store.create_session(store.create_project("one"))
    prefix = "A" * 800
    store.append(session, "user", prefix + "OLD")
    context = build_context(store, session, prefix + "NEW")
    assert len(context["history"]) == 1
    assert context["history"][0]["text"] == prefix
