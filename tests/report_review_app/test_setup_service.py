import json
import socket
import ssl
from pathlib import Path
from urllib.error import HTTPError, URLError

import pytest

from asset_based_agent.report_review_app.services.auth_service import AuthService
from asset_based_agent.report_review_app.services.setup_service import (
    ModelDiscoveryError,
    ReportReviewSetupService,
    SetupValidationError,
)


def test_create_accounts_preserves_existing_users(tmp_path: Path) -> None:
    users_path = tmp_path / "users.json"
    service = ReportReviewSetupService(
        users_path=users_path,
        model_config_path=tmp_path / "model_config.json",
    )

    service.create_or_update_account(
        username="reviewer",
        display_name="Reviewer",
        password="StrongPass123!",
        confirmation="StrongPass123!",
    )
    service.create_or_update_account(
        username="manager",
        display_name="Manager",
        password="AnotherPass123!",
        confirmation="AnotherPass123!",
    )

    payload = json.loads(users_path.read_text(encoding="utf-8"))
    assert [item["username"] for item in payload["users"]] == [
        "reviewer",
        "manager",
    ]
    assert AuthService(users_path).authenticate("reviewer", "StrongPass123!")
    assert AuthService(users_path).authenticate("manager", "AnotherPass123!")


def test_update_account_replaces_only_selected_user(tmp_path: Path) -> None:
    users_path = tmp_path / "users.json"
    service = ReportReviewSetupService(
        users_path=users_path,
        model_config_path=tmp_path / "model_config.json",
    )
    service.create_or_update_account(
        username="reviewer",
        display_name="Old",
        password="StrongPass123!",
        confirmation="StrongPass123!",
    )
    service.create_or_update_account(
        username="manager",
        display_name="Manager",
        password="AnotherPass123!",
        confirmation="AnotherPass123!",
    )

    service.create_or_update_account(
        username="reviewer",
        display_name="New",
        password="UpdatedPass123!",
        confirmation="UpdatedPass123!",
    )

    assert AuthService(users_path).authenticate("reviewer", "UpdatedPass123!")[
        "display_name"
    ] == "New"
    assert AuthService(users_path).authenticate("manager", "AnotherPass123!")


def test_save_api_config_preserves_existing_key_when_blank(tmp_path: Path) -> None:
    model_config_path = tmp_path / "model_config.json"
    service = ReportReviewSetupService(
        users_path=tmp_path / "users.json",
        model_config_path=model_config_path,
    )
    service.save_api_config(
        api_base="https://api.example.com/",
        api_key="secret-key",
        model="review-model",
        provider="openai-compatible",
        wire_api="responses",
    )

    service.save_api_config(
        api_base="https://api.example.com/v2/",
        api_key="",
        model="review-model-v2",
        provider="openai-compatible",
        wire_api="chat_completions",
    )

    payload = json.loads(model_config_path.read_text(encoding="utf-8"))
    assert payload == {
        "api_base": "https://api.example.com/v2",
        "api_key": "secret-key",
        "model": "review-model-v2",
        "provider": "openai-compatible",
        "wire_api": "chat_completions",
    }
    status = service.load_api_config_status()
    assert status.api_key_configured is True
    assert status.api_key == ""


@pytest.mark.parametrize(
    ("api_base", "api_key", "model"),
    [
        ("example.com", "secret", "model"),
        ("https://api.example.com", "", "model"),
        ("https://api.example.com", "secret", ""),
    ],
)
def test_save_api_config_rejects_incomplete_values(
    tmp_path: Path,
    api_base: str,
    api_key: str,
    model: str,
) -> None:
    service = ReportReviewSetupService(
        users_path=tmp_path / "users.json",
        model_config_path=tmp_path / "model_config.json",
    )

    with pytest.raises(SetupValidationError):
        service.save_api_config(
            api_base=api_base,
            api_key=api_key,
            model=model,
            provider="openai-compatible",
            wire_api="responses",
        )


def test_discover_models_normalizes_v1_and_sorts_unique_ids(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = ReportReviewSetupService(
        users_path=tmp_path / "users.json",
        model_config_path=tmp_path / "model_config.json",
    )
    captured: dict[str, object] = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self) -> bytes:
            return json.dumps(
                {
                    "data": [
                        {"id": "model-z"},
                        {"id": "model-a"},
                        {"id": "model-z"},
                    ]
                }
            ).encode()

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["authorization"] = request.get_header("Authorization")
        captured["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr(
        "asset_based_agent.report_review_app.services.setup_service.request.urlopen",
        fake_urlopen,
    )

    models = service.discover_models(
        api_base="https://api.example.com/v1/",
        api_key="secret-key",
    )

    assert models == ["model-a", "model-z"]
    assert captured == {
        "url": "https://api.example.com/v1/models",
        "authorization": "Bearer secret-key",
        "timeout": 20,
    }


def test_discover_models_uses_deepseek_official_models_endpoint(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = ReportReviewSetupService(
        users_path=tmp_path / "users.json",
        model_config_path=tmp_path / "model_config.json",
    )
    captured: dict[str, str] = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self) -> bytes:
            return b'{"data":[{"id":"deepseek-v4-pro"}]}'

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        return FakeResponse()

    monkeypatch.setattr(
        "asset_based_agent.report_review_app.services.setup_service.request.urlopen",
        fake_urlopen,
    )

    assert service.discover_models(
        api_base="https://api.deepseek.com",
        api_key="deepseek-key",
        provider="deepseek",
    ) == ["deepseek-v4-pro"]
    assert captured["url"] == "https://api.deepseek.com/models"


def test_save_api_config_rejects_responses_for_deepseek(tmp_path: Path) -> None:
    service = ReportReviewSetupService(
        users_path=tmp_path / "users.json",
        model_config_path=tmp_path / "model_config.json",
    )

    with pytest.raises(SetupValidationError, match="DeepSeek"):
        service.save_api_config(
            api_base="https://api.deepseek.com",
            api_key="deepseek-key",
            model="deepseek-v4-pro",
            provider="deepseek",
            wire_api="responses",
        )


def test_save_official_deepseek_url_normalizes_provider_and_wire_api(
    tmp_path: Path,
) -> None:
    model_config_path = tmp_path / "model_config.json"
    service = ReportReviewSetupService(
        users_path=tmp_path / "users.json",
        model_config_path=model_config_path,
    )

    service.save_api_config(
        api_base="https://api.deepseek.com/",
        api_key="deepseek-key",
        model="discovered-model",
        provider="openai-compatible",
        wire_api="responses",
    )

    payload = json.loads(model_config_path.read_text(encoding="utf-8"))
    assert payload["api_base"] == "https://api.deepseek.com"
    assert payload["provider"] == "deepseek"
    assert payload["wire_api"] == "chat_completions"


def test_discover_models_retries_transient_dns_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = ReportReviewSetupService(
        users_path=tmp_path / "users.json",
        model_config_path=tmp_path / "model_config.json",
    )
    attempts: list[int] = []
    delays: list[float] = []
    progress: list[tuple[int, int]] = []

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self) -> bytes:
            return b'{"data":[{"id":"deepseek-v4-pro"}]}'

    def fake_urlopen(*_args, **_kwargs):
        attempts.append(1)
        if len(attempts) < 3:
            raise URLError(socket.gaierror(11001, "getaddrinfo failed"))
        return FakeResponse()

    monkeypatch.setattr(
        "asset_based_agent.report_review_app.services.setup_service.request.urlopen",
        fake_urlopen,
    )
    monkeypatch.setattr(
        "asset_based_agent.report_review_app.services.setup_service.time.sleep",
        delays.append,
    )

    models = service.discover_models(
        api_base="https://api.deepseek.com",
        api_key="deepseek-secret-key",
        provider="deepseek",
        progress_callback=lambda attempt, total: progress.append((attempt, total)),
    )

    assert models == ["deepseek-v4-pro"]
    assert len(attempts) == 3
    assert delays == [1.0, 2.0]
    assert progress == [(1, 3), (2, 3), (3, 3)]


def test_discover_models_reports_dns_failure_without_leaking_key(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = ReportReviewSetupService(
        users_path=tmp_path / "users.json",
        model_config_path=tmp_path / "model_config.json",
    )
    attempts: list[int] = []
    monkeypatch.setattr(
        "asset_based_agent.report_review_app.services.setup_service.request.urlopen",
        lambda *_args, **_kwargs: (
            attempts.append(1),
            (_ for _ in ()).throw(
                URLError(socket.gaierror(11001, "getaddrinfo failed"))
            ),
        )[1],
    )
    monkeypatch.setattr(
        "asset_based_agent.report_review_app.services.setup_service.time.sleep",
        lambda _delay: None,
    )

    with pytest.raises(ModelDiscoveryError) as exc_info:
        service.discover_models(
            api_base="https://api.deepseek.com",
            api_key="deepseek-secret-key",
            provider="deepseek",
        )

    message = str(exc_info.value)
    assert len(attempts) == 3
    assert "DNS" in message
    assert "自动重试 2 次" in message
    assert "deepseek-secret-key" not in message


@pytest.mark.parametrize(
    ("status_code", "expected_text", "expected_attempts"),
    [
        (400, "HTTP 400", 1),
        (401, "API Key 无效", 1),
        (403, "访问权限", 1),
        (429, "请求频率", 3),
        (502, "暂时不可用", 3),
        (503, "暂时不可用", 3),
        (504, "暂时不可用", 3),
    ],
)
def test_discover_models_classifies_http_failures(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    status_code: int,
    expected_text: str,
    expected_attempts: int,
) -> None:
    service = ReportReviewSetupService(
        users_path=tmp_path / "users.json",
        model_config_path=tmp_path / "model_config.json",
    )
    attempts: list[int] = []

    def fake_urlopen(request, timeout):
        attempts.append(1)
        raise HTTPError(request.full_url, status_code, "failure", {}, None)

    monkeypatch.setattr(
        "asset_based_agent.report_review_app.services.setup_service.request.urlopen",
        fake_urlopen,
    )
    monkeypatch.setattr(
        "asset_based_agent.report_review_app.services.setup_service.time.sleep",
        lambda _delay: None,
    )

    with pytest.raises(ModelDiscoveryError, match=expected_text):
        service.discover_models(
            api_base="https://api.deepseek.com",
            api_key="deepseek-key",
            provider="deepseek",
        )

    assert len(attempts) == expected_attempts


def test_discover_models_retries_timeout_with_specific_message(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = ReportReviewSetupService(
        users_path=tmp_path / "users.json",
        model_config_path=tmp_path / "model_config.json",
    )
    attempts: list[int] = []

    def fake_urlopen(*_args, **_kwargs):
        attempts.append(1)
        raise URLError(TimeoutError("timed out"))

    monkeypatch.setattr(
        "asset_based_agent.report_review_app.services.setup_service.request.urlopen",
        fake_urlopen,
    )
    monkeypatch.setattr(
        "asset_based_agent.report_review_app.services.setup_service.time.sleep",
        lambda _delay: None,
    )

    with pytest.raises(ModelDiscoveryError, match="连接 DeepSeek 超时"):
        service.discover_models(
            api_base="https://api.deepseek.com",
            api_key="deepseek-key",
            provider="deepseek",
        )

    assert len(attempts) == 3


def test_discover_models_reports_tls_failure_without_retry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = ReportReviewSetupService(
        users_path=tmp_path / "users.json",
        model_config_path=tmp_path / "model_config.json",
    )
    attempts: list[int] = []

    def fake_urlopen(*_args, **_kwargs):
        attempts.append(1)
        raise URLError(ssl.SSLCertVerificationError("certificate verify failed"))

    monkeypatch.setattr(
        "asset_based_agent.report_review_app.services.setup_service.request.urlopen",
        fake_urlopen,
    )

    with pytest.raises(ModelDiscoveryError, match="证书校验失败"):
        service.discover_models(
            api_base="https://api.deepseek.com",
            api_key="deepseek-key",
            provider="deepseek",
        )

    assert len(attempts) == 1


def test_discover_models_uses_saved_key_when_input_is_blank(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model_config_path = tmp_path / "model_config.json"
    model_config_path.write_text(
        json.dumps(
            {
                "api_base": "https://old.example.com",
                "api_key": "saved-key",
                "model": "old-model",
            }
        ),
        encoding="utf-8",
    )
    service = ReportReviewSetupService(
        users_path=tmp_path / "users.json",
        model_config_path=model_config_path,
    )

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self) -> bytes:
            return b'{"data":[{"id":"available-model"}]}'

    def fake_urlopen(request, timeout):
        assert request.get_header("Authorization") == "Bearer saved-key"
        return FakeResponse()

    monkeypatch.setattr(
        "asset_based_agent.report_review_app.services.setup_service.request.urlopen",
        fake_urlopen,
    )

    assert service.discover_models(
        api_base="https://new.example.com",
        api_key="",
    ) == ["available-model"]


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"data": []},
        {"data": [{"name": "missing-id"}]},
    ],
)
def test_discover_models_rejects_missing_compatible_model_list(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    payload: dict[str, object],
) -> None:
    service = ReportReviewSetupService(
        users_path=tmp_path / "users.json",
        model_config_path=tmp_path / "model_config.json",
    )

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self) -> bytes:
            return json.dumps(payload).encode()

    monkeypatch.setattr(
        "asset_based_agent.report_review_app.services.setup_service.request.urlopen",
        lambda *_args, **_kwargs: FakeResponse(),
    )

    with pytest.raises(ModelDiscoveryError, match="模型列表"):
        service.discover_models(
            api_base="https://api.example.com",
            api_key="secret-key",
        )
