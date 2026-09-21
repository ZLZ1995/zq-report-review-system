import pytest

from asset_based_agent.technical_platform.diagnostics import failure_message
from asset_based_agent.technical_platform.store import PlatformStore


@pytest.mark.parametrize("phase,label", [
    ("planning", "计划校验"), ("context", "上下文构建"),
    ("execution", "执行"), ("validation", "结果校验"),
])
def test_failure_phase_is_actionable_without_raw_secrets(tmp_path, phase, label):
    store = PlatformStore(tmp_path / "db.sqlite", "alice")
    session = store.create_session(store.create_project("one"))
    run = store.start_run(session, {"files": []})
    store.transition(run, "failed", f"{phase}: ValueError sk-private-token")
    message = failure_message(store, run)
    assert label in message
    assert run in message
    assert "sk-private-token" not in message
    if phase == "validation":
        assert "不能作为已验收结果" in message
    if phase == "execution":
        assert "不要连续重复提交" in message


def test_diagnostics_cannot_read_other_account_and_does_not_call_running_run_failed(tmp_path):
    store = PlatformStore(tmp_path / "db.sqlite", "alice")
    session = store.create_session(store.create_project("one"))
    run = store.start_run(session, {"files": []})
    store.claim_run(run)
    assert "正在执行" in failure_message(store, run)
    with pytest.raises(PermissionError):
        failure_message(PlatformStore(store.path, "bob"), run)


def test_legacy_unknown_failure_does_not_invent_phase(tmp_path):
    store = PlatformStore(tmp_path / "db.sqlite", "alice")
    session = store.create_session(store.create_project("one"))
    run = store.start_run(session, {"files": []})
    store.transition(run, "failed", "unstructured secret")
    assert "未记录" in failure_message(store, run)
    assert "secret" not in failure_message(store, run)


def test_failure_message_surfaces_safe_worker_reason(tmp_path):
    store = PlatformStore(tmp_path / "db.sqlite", "alice")
    session = store.create_session(store.create_project("one"))
    run = store.start_run(session, {"files": []})
    store.transition(run, "failed", "execution: ValueError")
    message = failure_message(store, run, worker_message="存在多份同类资料，需要先确认本轮使用的主体和期间")
    assert "存在多份同类资料" in message
    assert run in message


def test_failure_message_drops_unsafe_worker_reason(tmp_path):
    store = PlatformStore(tmp_path / "db.sqlite", "alice")
    session = store.create_session(store.create_project("one"))
    run = store.start_run(session, {"files": []})
    store.transition(run, "failed", "execution: ValueError")
    for unsafe in ("401 https://internal.example/token=abc", "Bearer sk-live-secret-key",
                   "Traceback (most recent call last)", "x" * 300, ""):
        message = failure_message(store, run, worker_message=unsafe)
        assert unsafe not in message or not unsafe
