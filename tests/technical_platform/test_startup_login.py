import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from asset_based_agent.technical_platform import app as platform


def test_cancel_login_never_opens_workspace_or_directory(monkeypatch):
    qt = QApplication.instance() or QApplication([])
    assert qt
    monkeypatch.setattr(sys, "argv", ["platform"])
    monkeypatch.setattr(platform, "authenticate", lambda parent=None: None)
    monkeypatch.setattr(platform.QFileDialog, "getExistingDirectory", lambda *a: (_ for _ in ()).throw(AssertionError("directory before login")))
    monkeypatch.setattr(platform, "PlatformWindow", lambda *a, **kw: (_ for _ in ()).throw(AssertionError("workspace before login")))
    assert platform.main() == 0


def test_successful_login_precedes_directory_and_window(monkeypatch, tmp_path):
    qt = QApplication.instance() or QApplication([])
    assert qt
    order = []
    client = object()
    payload = {"owner": "account-a", "models": [], "balance": {"balance": "100.00"}}
    monkeypatch.setattr(sys, "argv", ["platform"])
    def login(parent=None):
        order.append("login")
        return client, payload
    def directory(*args):
        order.append("directory")
        return str(tmp_path)
    class Window:
        def __init__(self, store, **kwargs):
            assert kwargs["client"] is client
            assert store.owner == "account-a"
            order.append("window")
        def balance_updated(self, value):
            assert value == "100.00"
        def show(self):
            order.append("show")
    monkeypatch.setattr(platform, "authenticate", login)
    monkeypatch.setattr(platform.QFileDialog, "getExistingDirectory", directory)
    monkeypatch.setattr(platform, "PlatformWindow", Window)
    monkeypatch.setattr(QApplication, "exec", lambda self: 0)
    assert platform.main() == 0
    assert order == ["login", "directory", "window", "show"]


def test_authentication_uses_embedded_url_without_prompt(monkeypatch, tmp_path):
    from asset_based_agent.report_review_app.services import remote_auth_service
    from asset_based_agent.technical_platform import login
    qt = QApplication.instance() or QApplication([])
    assert qt
    monkeypatch.setenv("ZQ_REPORT_REVIEW_SERVER_URL", "https://wrong.example/api/v1")
    monkeypatch.setattr(platform.QStandardPaths, "writableLocation", lambda *a: str(tmp_path))
    observed = []
    class Client:
        def __init__(self, url, **kwargs):
            observed.append(url)
            self.http_client = self
        def close(self):
            observed.append("closed")
    class Dialog:
        def __init__(self, service, parent):
            pass
        def exec(self):
            return platform.QDialog.DialogCode.Rejected
    monkeypatch.setattr(remote_auth_service, "RemoteSessionClient", Client)
    monkeypatch.setattr(login, "PlatformLogin", Dialog)
    monkeypatch.setattr(platform.QInputDialog, "getText", lambda *a, **kw: (_ for _ in ()).throw(AssertionError("URL prompt")))
    assert platform.authenticate() is None
    assert observed == ["https://zq-report-review.zeabur.app/api/v1", "closed"]


def test_offline_startup_needs_no_client_or_balance(monkeypatch, tmp_path):
    qt = QApplication.instance() or QApplication([])
    assert qt
    monkeypatch.setattr(sys, "argv", ["platform", "--data-dir", str(tmp_path)])
    monkeypatch.setattr(platform, "authenticate", lambda: (None, {
        "owner": "offline-local", "models": [], "offline": True,
    }))
    class Window:
        def __init__(self, store, **kwargs):
            assert store.owner == "offline-local"
            assert kwargs["client"] is None
        def show(self):
            pass
        def balance_updated(self, value):
            raise AssertionError("offline balance must not be fabricated")
    monkeypatch.setattr(platform, "PlatformWindow", Window)
    monkeypatch.setattr(QApplication, "exec", lambda self: 0)
    assert platform.main() == 0
