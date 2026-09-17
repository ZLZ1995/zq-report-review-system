import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from asset_based_agent.technical_platform.app import PlatformWindow
from asset_based_agent.technical_platform.skills import REVIEW
from asset_based_agent.technical_platform.store import PlatformStore


def test_switch_account_clears_previous_project_and_conversation(monkeypatch, tmp_path):
    from asset_based_agent.technical_platform import app as platform
    app = QApplication.instance() or QApplication([])
    assert app
    store = PlatformStore(tmp_path / "state.db", "account-a")
    project = store.create_project("private-a")
    session = store.create_session(project)
    store.append(session, "user", "ACCOUNT_A_SECRET")
    other = PlatformStore(store.path, "account-b")
    other.create_project("private-b")
    window = PlatformWindow(store)
    window.reload_projects(project)
    window.composer.setPlainText("PRIVATE_DRAFT")
    monkeypatch.setattr(platform, "authenticate", lambda parent: (
        object(), {"owner": "account-b", "models": [], "balance": {"balance": "1.00"}}
    ))
    try:
        assert window.connect_service()
        assert window.store.owner == "account-b"
        assert "ACCOUNT_A_SECRET" not in window.transcript.toPlainText()
        assert window.composer.toPlainText() == ""
        assert window.project_id is None
        assert window.session_id is None
        assert [p["name"] for p in window.store.projects()] == ["private-b"]
        assert store.messages(session)[0]["text"] == "ACCOUNT_A_SECRET"
    finally:
        window.close()


def test_offline_keeps_review_visible_and_local_actions_enabled(tmp_path):
    app = QApplication.instance() or QApplication([])
    assert app
    window = PlatformWindow(PlatformStore(tmp_path / "state.db", "local-preview"))
    try:
        assert not hasattr(window, 'skill_combo')
        window.connection_changed("reconnecting")
        assert window.send.isEnabled()
        assert window.attach.isEnabled()
    finally:
        window.close()


def test_cancelled_connection_keeps_prompt_and_history(tmp_path):
    app = QApplication.instance() or QApplication([])
    assert app
    store = PlatformStore(tmp_path / "state.db", "local-preview")
    project = store.create_project("local")
    session = store.create_session(project)
    window = PlatformWindow(store)
    window.reload_projects(project)
    source = tmp_path / 'report.docx'
    source.write_bytes(b'fixture')
    window.import_files([source])
    window.composer.setPlainText("审核报告")
    called = []
    window.connect_service = lambda: called.append(True) or False
    try:
        window.submit()
        assert called == [True]
        assert window.composer.toPlainText() == "审核报告"
        assert store.runs(session) == []
    finally:
        window.close()
