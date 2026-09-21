"""Safe local configuration service for report-review accounts and LLM access."""

from __future__ import annotations

import json
import os
import socket
import ssl
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib import request
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse

from .auth_service import build_password_record


class SetupValidationError(ValueError):
    """Raised when account or API configuration is incomplete or unsafe."""


class ModelDiscoveryError(RuntimeError):
    """Raised when an OpenAI-compatible model list cannot be obtained."""


_MODEL_DISCOVERY_ATTEMPTS = 3
_MODEL_DISCOVERY_RETRY_DELAYS = (1.0, 2.0)
_RETRYABLE_HTTP_STATUS_CODES = {429, 502, 503, 504}


@dataclass(frozen=True)
class ApiConfigStatus:
    api_base: str = ""
    api_key: str = ""
    model: str = ""
    provider: str = "openai-compatible"
    wire_api: str = "chat_completions"
    api_key_configured: bool = False


def default_model_config_path() -> Path:
    return Path.home() / ".ai-excel-agent" / "model_config.json"


class ReportReviewSetupService:
    def __init__(
        self,
        *,
        users_path: Path,
        model_config_path: Path | None = None,
    ) -> None:
        self.users_path = Path(users_path)
        self.model_config_path = Path(
            model_config_path or default_model_config_path()
        )

    def create_or_update_account(
        self,
        *,
        username: str,
        display_name: str,
        password: str,
        confirmation: str,
    ) -> Path:
        normalized_username = username.strip()
        if len(normalized_username) < 2 or len(normalized_username) > 64:
            raise SetupValidationError("用户名长度必须为 2 至 64 个字符。")
        if any(character.isspace() or ord(character) < 32 for character in normalized_username):
            raise SetupValidationError("用户名不能包含空白字符或控制字符。")
        if len(password) < 8:
            raise SetupValidationError("密码长度不能少于 8 个字符。")
        if password != confirmation:
            raise SetupValidationError("两次输入的密码不一致。")

        payload = self._load_users_payload()
        users = list(payload.get("users") or [])
        replacement = {
            "username": normalized_username,
            "display_name": display_name.strip() or normalized_username,
            "enabled": True,
            "password": build_password_record(password),
        }
        for index, user in enumerate(users):
            if isinstance(user, dict) and user.get("username") == normalized_username:
                users[index] = replacement
                break
        else:
            users.append(replacement)
        payload["schema_version"] = "1.0"
        payload["users"] = users
        _write_json_atomic(self.users_path, payload)
        return self.users_path

    def load_api_config_status(self) -> ApiConfigStatus:
        payload = _read_json_object(self.model_config_path, allow_missing=True)
        wire_api = str(payload.get("wire_api") or "chat_completions")
        if wire_api not in {"chat_completions", "responses"}:
            wire_api = "chat_completions"
        provider = str(payload.get("provider") or "openai-compatible")
        if _is_official_deepseek_url(str(payload.get("api_base") or "")):
            provider = "deepseek"
            wire_api = "chat_completions"
        return ApiConfigStatus(
            api_base=str(payload.get("api_base") or ""),
            model=str(payload.get("model") or ""),
            provider=provider,
            wire_api=wire_api,
            api_key_configured=bool(payload.get("api_key")),
        )

    def save_api_config(
        self,
        *,
        api_base: str,
        api_key: str,
        model: str,
        provider: str,
        wire_api: str,
    ) -> Path:
        normalized_base = api_base.strip().rstrip("/")
        parsed = urlparse(normalized_base)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise SetupValidationError("API 地址必须是完整的 HTTP 或 HTTPS 地址。")
        normalized_model = model.strip()
        if not normalized_model:
            raise SetupValidationError("模型名称不能为空。")
        normalized_provider = provider.strip() or "openai-compatible"
        if wire_api not in {"chat_completions", "responses"}:
            raise SetupValidationError("接口类型无效。")
        if normalized_provider == "deepseek" and wire_api != "chat_completions":
            raise SetupValidationError(
                "DeepSeek 官方 API 仅支持 chat_completions 接口类型。"
            )
        if _is_official_deepseek_url(normalized_base):
            normalized_provider = "deepseek"
            wire_api = "chat_completions"

        existing = _read_json_object(self.model_config_path, allow_missing=True)
        effective_key = api_key.strip() or str(existing.get("api_key") or "")
        if not effective_key:
            raise SetupValidationError("首次配置时必须录入 API Key。")
        payload = {
            "api_base": normalized_base,
            "api_key": effective_key,
            "model": normalized_model,
            "provider": normalized_provider,
            "wire_api": wire_api,
        }
        _write_json_atomic(self.model_config_path, payload)
        return self.model_config_path

    def discover_models(
        self,
        *,
        api_base: str,
        api_key: str,
        provider: str = "openai-compatible",
        progress_callback: Callable[[int, int], None] | None = None,
    ) -> list[str]:
        normalized_base = self._validate_api_base(api_base)
        effective_key = self._effective_api_key(api_key)
        normalized_provider = (
            "deepseek" if _is_official_deepseek_url(normalized_base) else provider
        )
        endpoint = _models_endpoint(normalized_base, provider=normalized_provider)
        api_request = request.Request(
            endpoint,
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {effective_key}",
            },
            method="GET",
        )
        payload = _request_model_list(
            api_request,
            provider=provider,
            progress_callback=progress_callback,
        )

        if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
            raise ModelDiscoveryError(
                "该服务未返回兼容的模型列表（预期格式为 data[].id）。"
            )
        model_ids = {
            str(item["id"]).strip()
            for item in payload["data"]
            if isinstance(item, dict) and str(item.get("id") or "").strip()
        }
        if not model_ids:
            raise ModelDiscoveryError("模型列表为空，无法选择可用模型。")
        return sorted(model_ids, key=str.casefold)

    def has_effective_api_key(self, api_key: str) -> bool:
        return bool(api_key.strip()) or self.load_api_config_status().api_key_configured

    @staticmethod
    def _validate_api_base(api_base: str) -> str:
        normalized_base = api_base.strip().rstrip("/")
        parsed = urlparse(normalized_base)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise SetupValidationError("API 地址必须是完整的 HTTP 或 HTTPS 地址。")
        return normalized_base

    def _effective_api_key(self, api_key: str) -> str:
        existing = _read_json_object(self.model_config_path, allow_missing=True)
        effective_key = api_key.strip() or str(existing.get("api_key") or "")
        if not effective_key:
            raise SetupValidationError("请先录入 API Key。")
        return effective_key

    def _load_users_payload(self) -> dict[str, Any]:
        payload = _read_json_object(self.users_path, allow_missing=True)
        if not payload:
            return {"schema_version": "1.0", "users": []}
        users = payload.get("users")
        if not isinstance(users, list):
            raise SetupValidationError("现有账号配置格式无效，未执行覆盖。")
        return payload


def _read_json_object(path: Path, *, allow_missing: bool) -> dict[str, Any]:
    if not path.exists():
        if allow_missing:
            return {}
        raise SetupValidationError(f"配置文件不存在：{path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SetupValidationError(f"配置文件无法读取：{path}") from exc
    if not isinstance(payload, dict):
        raise SetupValidationError(f"配置文件必须为 JSON 对象：{path}")
    return payload


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _models_endpoint(api_base: str, *, provider: str) -> str:
    if api_base.lower().endswith("/v1"):
        return api_base + "/models"
    if provider == "deepseek":
        return api_base + "/models"
    return api_base + "/v1/models"


def _is_official_deepseek_url(api_base: str) -> bool:
    return (urlparse(api_base.strip()).hostname or "").lower() == "api.deepseek.com"


def _request_model_list(
    api_request: request.Request,
    *,
    provider: str,
    progress_callback: Callable[[int, int], None] | None,
) -> Any:
    for attempt in range(1, _MODEL_DISCOVERY_ATTEMPTS + 1):
        if progress_callback is not None:
            progress_callback(attempt, _MODEL_DISCOVERY_ATTEMPTS)
        try:
            with request.urlopen(api_request, timeout=20) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            should_retry = exc.code in _RETRYABLE_HTTP_STATUS_CODES
            if should_retry and attempt < _MODEL_DISCOVERY_ATTEMPTS:
                _wait_before_retry(attempt)
                continue
            raise ModelDiscoveryError(
                _http_failure_message(
                    exc.code,
                    provider=provider,
                    retried=should_retry,
                )
            ) from exc
        except (
            URLError,
            TimeoutError,
            ConnectionResetError,
            ConnectionAbortedError,
            ssl.SSLError,
        ) as exc:
            failure_kind = _network_failure_kind(exc)
            should_retry = failure_kind != "tls"
            if should_retry and attempt < _MODEL_DISCOVERY_ATTEMPTS:
                _wait_before_retry(attempt)
                continue
            raise ModelDiscoveryError(
                _network_failure_message(
                    failure_kind,
                    provider=provider,
                    retried=should_retry,
                    host=urlparse(api_request.full_url).hostname or "API 服务",
                )
            ) from exc
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ModelDiscoveryError(
                "模型服务返回了无法识别的响应，请确认其兼容所选 API 类型。"
            ) from exc
    raise ModelDiscoveryError("模型服务连接测试未能完成。")


def _wait_before_retry(attempt: int) -> None:
    time.sleep(_MODEL_DISCOVERY_RETRY_DELAYS[attempt - 1])


def _network_failure_kind(exc: BaseException) -> str:
    reason = exc.reason if isinstance(exc, URLError) else exc
    message = str(reason).lower()
    if isinstance(reason, socket.gaierror) or "getaddrinfo" in message:
        return "dns"
    if isinstance(reason, ssl.SSLError) or any(
        marker in message
        for marker in ("certificate", "ssl", "tls")
    ):
        return "tls"
    if isinstance(reason, (TimeoutError, socket.timeout)) or "timed out" in message:
        return "timeout"
    return "connection"


def _network_failure_message(
    failure_kind: str,
    *,
    provider: str,
    retried: bool,
    host: str,
) -> str:
    service_name = _service_name(provider)
    retry_note = "程序已自动重试 2 次。" if retried else ""
    if failure_kind == "dns":
        return f"无法解析 {host}，请检查 DNS 或网络代理。{retry_note}"
    if failure_kind == "timeout":
        return f"连接 {service_name} 超时。{retry_note}"
    if failure_kind == "tls":
        return "HTTPS 证书校验失败，请检查系统时间、代理或证书环境。"
    return f"无法连接 {service_name}，请检查网络和 API 地址。{retry_note}"


def _http_failure_message(
    status_code: int,
    *,
    provider: str,
    retried: bool,
) -> str:
    if status_code == 401:
        return "API Key 无效或已失效。"
    if status_code == 403:
        return "API Key 没有访问权限，请检查余额、权限或 IP 限制。"
    if status_code == 429:
        return "请求频率过高或额度不足，程序已自动重试 2 次，请稍后重试。"
    if status_code in {502, 503, 504}:
        return (
            f"{_service_name(provider)}暂时不可用，"
            "程序已自动重试 2 次，请稍后重试。"
        )
    retry_note = "程序已自动重试 2 次。" if retried else ""
    return (
        f"模型列表接口返回 HTTP {status_code}，请核对 URL 和 API Key。"
        f"{retry_note}"
    )


def _service_name(provider: str) -> str:
    return "DeepSeek" if provider == "deepseek" else "模型服务"
