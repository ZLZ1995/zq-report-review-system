import os
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication

from asset_based_agent.technical_platform.login import PlatformLogin


def test_offline_entry_never_calls_login_and_has_separate_owner():
    app = QApplication.instance() or QApplication([])
    assert app
    dialog = PlatformLogin(None)
    dialog.offline_button.click()
    assert dialog.result_payload["offline"] is True
    assert dialog.result_payload["owner"] == "offline-local"
    assert dialog.result_payload["models"] == []


def settle(app, dialog):
    deadline = time.monotonic() + 5
    while dialog.worker is not None and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.01)
    assert dialog.worker is None


def test_login_window_requires_confirmed_password_change_before_accepting():
    app = QApplication.instance() or QApplication([])

    class Service:
        def login(self, username, password):
            return {"must_change_password": True}

        def change_password(self, current, new):
            assert current == "temporary" and new == "new-password"
            return {"must_change_password": False, "owner": "owner", "models": []}

    dialog = PlatformLogin(Service())
    dialog.username.setText("tester")
    dialog.password.setText("temporary")
    dialog.submit()
    settle(app, dialog)
    assert dialog.changing and dialog.result_payload is None
    assert dialog.password.text() == ""
    dialog.password.setText("temporary")
    dialog.new_password.setText("new-password")
    dialog.confirm_password.setText("different")
    dialog.submit()
    assert dialog.worker is None and dialog.result_payload is None
    dialog.confirm_password.setText("new-password")
    dialog.submit()
    settle(app, dialog)
    assert dialog.result_payload["owner"] == "owner"
    assert dialog.new_password.text() == ""


def test_login_window_failed_login_does_not_leak_error_details():
    app = QApplication.instance() or QApplication([])

    class Service:
        def login(self, username, password):
            raise ValueError("sensitive_debug_detail")

    dialog = PlatformLogin(Service())
    dialog.username.setText("tester")
    dialog.password.setText("temporary")
    dialog.submit()
    settle(app, dialog)
    assert "sensitive_debug_detail" not in dialog.error.text()
    assert dialog.result_payload is None and dialog.password.text() == ""


def test_login_window_explains_credential_save_failure():
    app = QApplication.instance() or QApplication([])
    assert app
    dialog = PlatformLogin(None)
    dialog.failed("CredentialStorageError: 本机安全凭据保存失败，请检查 Windows 凭据管理器。")
    assert dialog.error.text() == "本机安全凭据保存失败，请检查 Windows 凭据管理器。"
    dialog.failed("ValueError: secret-sensitive-detail")
    assert "secret-sensitive-detail" not in dialog.error.text()
