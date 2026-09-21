import os
import threading
import time
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QApplication

from asset_based_agent.report_review_app.config_tool import ConfigToolWindow
from asset_based_agent.report_review_app.services.auth_service import AuthService
from asset_based_agent.report_review_app.services.setup_service import (
    ModelDiscoveryError,
    ReportReviewSetupService,
)


def application() -> QApplication:
    return QApplication.instance() or QApplication([])


def wait_until(predicate, timeout: float = 2.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        application().processEvents()
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("condition was not met before timeout")


@pytest.fixture(autouse=True)
def cleanup_config_windows(monkeypatch):
    """Keep Qt owners alive until native workers have finished teardown."""
    app = application()
    windows = []
    original = ConfigToolWindow.__init__

    def capture(window, *args, **kwargs):
        original(window, *args, **kwargs)
        windows.append(window)

    monkeypatch.setattr(ConfigToolWindow, "__init__", capture)
    yield
    for window in windows:
        wait_until(lambda window=window: window._model_thread is None, timeout=5)
        window.close()
        window.deleteLater()
    app.processEvents()


@pytest.mark.parametrize("outcome", ["success", "failure"])
def test_result_does_not_allow_restart_before_thread_cleanup(tmp_path, monkeypatch, outcome):
    release = threading.Event()
    service = ReportReviewSetupService(users_path=tmp_path / "u.json", model_config_path=tmp_path / "m.json")
    monkeypatch.setattr(service, "discover_models", lambda **kw: (release.wait(3), ["model"])[1])
    window = ConfigToolWindow(service)
    window.api_base_input.setText("https://example.com")
    window.api_key_input.setText("fake")
    window.api_test_button.click()
    thread = window._model_thread
    try:
        if outcome == "success":
            window._model_discovery_succeeded(["model"])
        else:
            window._model_discovery_failed("test error")
        assert not window.api_test_button.isEnabled()
        assert not window.api_base_input.isEnabled()
        window._test_connection()
        assert window._model_thread is thread
    finally:
        release.set()
        wait_until(lambda: window._model_thread is None)


def test_close_during_model_discovery_waits_without_blocking_ui(tmp_path, monkeypatch):
    release = threading.Event()
    service = ReportReviewSetupService(users_path=tmp_path / "u.json", model_config_path=tmp_path / "m.json")
    monkeypatch.setattr(service, "discover_models", lambda **kw: (release.wait(3), ["model"])[1])
    window = ConfigToolWindow(service)
    window.show()
    window.api_base_input.setText("https://example.com")
    window.api_key_input.setText("fake")
    window.api_test_button.click()
    try:
        assert not window.close()
        assert window.isVisible()
    finally:
        release.set()
        wait_until(lambda: window._model_thread is None)
    wait_until(lambda: not window.isVisible())


def test_config_tool_saves_account_and_api(
    tmp_path: Path,
) -> None:
    application()
    users_path = tmp_path / "users.json"
    model_config_path = tmp_path / "model_config.json"
    window = ConfigToolWindow(
        ReportReviewSetupService(
            users_path=users_path,
            model_config_path=model_config_path,
        )
    )
    window.account_username_input.setText("reviewer")
    window.account_display_name_input.setText("Review User")
    window.account_password_input.setText("StrongPass123!")
    window.account_confirmation_input.setText("StrongPass123!")
    window.account_save_button.click()

    assert "保存成功" in window.account_status_label.text()
    assert AuthService(users_path).authenticate("reviewer", "StrongPass123!")
    assert window.account_password_input.text() == "StrongPass123!"

    window.api_base_input.setText("https://api.example.com")
    window.api_key_input.setText("secret-key")
    window._apply_discovered_models(["review-model"])
    window.api_model_input.setCurrentText("review-model")
    window.api_wire_input.setCurrentText("responses")
    window.api_save_button.click()

    assert "保存成功" in window.api_status_label.text()
    assert model_config_path.is_file()
    assert window.api_model_input.currentText() == "review-model"
    assert window.login_button.isEnabled()


def test_model_discovery_button_state_and_dropdown_population(
    tmp_path: Path,
    monkeypatch,
) -> None:
    application()
    service = ReportReviewSetupService(
        users_path=tmp_path / "users.json",
        model_config_path=tmp_path / "model_config.json",
    )
    window = ConfigToolWindow(service)

    assert not window.api_test_button.isEnabled()
    assert not window.api_model_input.isEditable()
    assert not window.api_save_button.isEnabled()

    window.api_base_input.setText("https://api.example.com/v1")
    assert not window.api_test_button.isEnabled()
    window.api_key_input.setText("secret-key")
    assert window.api_test_button.isEnabled()

    monkeypatch.setattr(
        service,
        "discover_models",
        lambda **_kwargs: ["model-z", "model-a"],
    )
    window.api_test_button.click()
    wait_until(lambda: window.api_model_input.count() == 2)

    assert [
        window.api_model_input.itemText(index)
        for index in range(window.api_model_input.count())
    ] == ["model-z", "model-a"]
    assert window.api_model_input.currentIndex() == -1
    assert not window.api_save_button.isEnabled()

    window.api_model_input.setCurrentIndex(1)
    assert window.api_save_button.isEnabled()
    assert "连接成功" in window.api_status_label.text()


def test_saved_api_key_enables_model_discovery_without_revealing_key(
    tmp_path: Path,
) -> None:
    application()
    model_config_path = tmp_path / "model_config.json"
    model_config_path.write_text(
        (
            '{"api_base":"https://api.example.com","api_key":"saved-key",'
            '"model":"saved-model","provider":"openai-compatible",'
            '"wire_api":"chat_completions"}'
        ),
        encoding="utf-8",
    )
    window = ConfigToolWindow(
        ReportReviewSetupService(
            users_path=tmp_path / "users.json",
            model_config_path=model_config_path,
        )
    )

    assert window.api_key_input.text() == ""
    assert window.api_test_button.isEnabled()
    assert window.api_model_input.currentText() == "saved-model"


def test_api_form_controls_have_clear_vertical_spacing(tmp_path: Path) -> None:
    application()
    window = ConfigToolWindow(
        ReportReviewSetupService(
            users_path=tmp_path / "users.json",
            model_config_path=tmp_path / "model_config.json",
        )
    )
    window.resize(860, 760)
    window.show()
    window.tabs.setCurrentIndex(1)
    application().processEvents()

    controls = [
        window.api_base_input,
        window.api_key_input,
        window.api_test_button,
        window.api_model_input,
        window.api_provider_input,
        window.api_wire_input,
        window.api_save_button,
    ]
    rectangles = [
        (
            control.mapTo(window, QPoint(0, 0)).y(),
            control.mapTo(window, QPoint(0, 0)).y() + control.height(),
        )
        for control in controls
    ]

    assert window.minimumWidth() >= 760
    assert window.minimumHeight() >= 680
    assert all(
        next_top - current_bottom >= 10
        for (_, current_bottom), (next_top, _) in zip(
            rectangles,
            rectangles[1:],
        )
    )


def test_selecting_deepseek_applies_official_api_preset(tmp_path: Path) -> None:
    application()
    window = ConfigToolWindow(
        ReportReviewSetupService(
            users_path=tmp_path / "users.json",
            model_config_path=tmp_path / "model_config.json",
        )
    )

    deepseek_index = window.api_provider_input.findData("deepseek")
    assert deepseek_index >= 0
    window.api_provider_input.setCurrentIndex(deepseek_index)

    assert window.api_base_input.text() == "https://api.deepseek.com"
    assert window.api_wire_input.currentText() == "chat_completions"
    assert not window.api_wire_input.isEnabled()


def test_model_discovery_shows_retry_progress_and_keeps_ui_responsive(
    tmp_path: Path,
    monkeypatch,
) -> None:
    application()
    release = threading.Event()
    service = ReportReviewSetupService(
        users_path=tmp_path / "users.json",
        model_config_path=tmp_path / "model_config.json",
    )

    def fake_discover_models(**kwargs):
        kwargs["progress_callback"](1, 3)
        kwargs["progress_callback"](2, 3)
        release.wait(timeout=2)
        return ["deepseek-v4-pro"]

    monkeypatch.setattr(service, "discover_models", fake_discover_models)
    window = ConfigToolWindow(service)
    window.api_base_input.setText("https://api.deepseek.com")
    window.api_key_input.setText("deepseek-key")
    window.api_test_button.click()

    wait_until(lambda: "第 2/3 次" in window.api_status_label.text())
    assert not window.api_base_input.isEnabled()
    assert not window.api_key_input.isEnabled()
    assert application().startingUp() is False

    release.set()
    wait_until(lambda: "连接成功" in window.api_status_label.text())
    wait_until(lambda: window._model_thread is None)
    assert window.api_base_input.isEnabled()
    assert window.api_key_input.isEnabled()


def test_model_discovery_failure_restores_inputs_without_saving(
    tmp_path: Path,
    monkeypatch,
) -> None:
    application()
    model_config_path = tmp_path / "model_config.json"
    service = ReportReviewSetupService(
        users_path=tmp_path / "users.json",
        model_config_path=model_config_path,
    )

    def fake_discover_models(**_kwargs):
        raise ModelDiscoveryError(
            "无法解析 api.deepseek.com，请检查 DNS 或网络代理。"
            "程序已自动重试 2 次。"
        )

    monkeypatch.setattr(service, "discover_models", fake_discover_models)
    window = ConfigToolWindow(service)
    window.api_base_input.setText("https://api.deepseek.com")
    window.api_key_input.setText("deepseek-key")
    window.api_test_button.click()

    wait_until(lambda: "DNS" in window.api_status_label.text())
    wait_until(lambda: window._model_thread is None)
    assert window.api_base_input.isEnabled()
    assert window.api_key_input.isEnabled()
    assert window.api_key_input.text() == "deepseek-key"
    assert not model_config_path.exists()


def test_login_saves_api_config_and_opens_authenticated_main_program(
    tmp_path: Path,
) -> None:
    application()
    users_path = tmp_path / "users.json"
    model_config_path = tmp_path / "model_config.json"
    service = ReportReviewSetupService(
        users_path=users_path,
        model_config_path=model_config_path,
    )
    service.create_or_update_account(
        username="reviewer",
        display_name="Review User",
        password="StrongPass123!",
        confirmation="StrongPass123!",
    )
    sessions: list[dict[str, str]] = []

    class FakeController:
        def start_authenticated(self, session):
            sessions.append(session)

    window = ConfigToolWindow(
        service,
        desktop_controller_factory=lambda _application: FakeController(),
    )
    window.show()
    deepseek_index = window.api_provider_input.findData("deepseek")
    window.api_provider_input.setCurrentIndex(deepseek_index)
    window.api_key_input.setText("deepseek-key")
    window._apply_discovered_models(["deepseek-v4-pro"])
    window.api_model_input.setCurrentIndex(0)
    window.account_username_input.setText("reviewer")
    window.account_password_input.setText("StrongPass123!")

    assert window.login_button.isEnabled()
    window.login_button.click()

    assert sessions == [
        {"username": "reviewer", "display_name": "Review User"}
    ]
    payload = model_config_path.read_text(encoding="utf-8")
    assert '"provider": "deepseek"' in payload
    assert '"model": "deepseek-v4-pro"' in payload
    assert window.isHidden()


def test_login_rejects_invalid_password_before_saving_api_config(
    tmp_path: Path,
) -> None:
    application()
    users_path = tmp_path / "users.json"
    model_config_path = tmp_path / "model_config.json"
    service = ReportReviewSetupService(
        users_path=users_path,
        model_config_path=model_config_path,
    )
    service.create_or_update_account(
        username="reviewer",
        display_name="Review User",
        password="StrongPass123!",
        confirmation="StrongPass123!",
    )
    controllers: list[object] = []
    window = ConfigToolWindow(
        service,
        desktop_controller_factory=lambda _application: controllers.append(
            object()
        ),
    )
    window.api_base_input.setText("https://api.example.com")
    window.api_key_input.setText("api-key")
    window._apply_discovered_models(["review-model"])
    window.api_model_input.setCurrentIndex(0)
    window.account_username_input.setText("reviewer")
    window.account_password_input.setText("wrong-password")

    window.login_button.click()

    assert "用户名或密码错误" in window.account_status_label.text()
    assert controllers == []
    assert not model_config_path.exists()


def test_login_button_requires_credentials_and_complete_api_selection(
    tmp_path: Path,
) -> None:
    application()
    window = ConfigToolWindow(
        ReportReviewSetupService(
            users_path=tmp_path / "users.json",
            model_config_path=tmp_path / "model_config.json",
        )
    )
    window.account_username_input.setText("reviewer")
    window.account_password_input.setText("StrongPass123!")
    assert not window.login_button.isEnabled()

    window.api_base_input.setText("https://api.example.com")
    window.api_key_input.setText("api-key")
    assert not window.login_button.isEnabled()

    window._apply_discovered_models(["review-model"])
    window.api_model_input.setCurrentIndex(0)
    assert window.login_button.isEnabled()
