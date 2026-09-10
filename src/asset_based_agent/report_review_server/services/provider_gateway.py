"""Provider calls and normalized Token usage."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import httpx

from ..crypto import SecretCipher
from ..models import ProviderRoute


@dataclass(frozen=True)
class NormalizedUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_hit_tokens: int = 0
    cache_miss_tokens: int = 0
    reasoning_tokens: int = 0

    def __post_init__(self) -> None:
        if any(value < 0 for value in self.values()):
            raise ValueError("Token usage cannot be negative")

    def values(self) -> tuple[int, int, int, int, int]:
        return (
            self.input_tokens,
            self.output_tokens,
            self.cache_hit_tokens,
            self.cache_miss_tokens,
            self.reasoning_tokens,
        )


@dataclass(frozen=True)
class ProviderResponse:
    payload: dict[str, object]
    usage: NormalizedUsage


class ProviderCallError(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        retryable: bool,
        usage: NormalizedUsage | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable
        self.usage = usage


class ProviderClient(Protocol):
    def call(
        self,
        route: ProviderRoute,
        payload: dict[str, object],
    ) -> ProviderResponse: ...


def normalize_openai_usage(payload: dict[str, object]) -> NormalizedUsage:
    prompt_tokens = _integer(payload.get("prompt_tokens"))
    completion_tokens = _integer(payload.get("completion_tokens"))
    cache_hit = _integer(payload.get("prompt_cache_hit_tokens"))
    cache_miss = _integer(payload.get("prompt_cache_miss_tokens"))
    details = payload.get("completion_tokens_details")
    reasoning = 0
    if isinstance(details, dict):
        reasoning = _integer(details.get("reasoning_tokens"))
    if not reasoning:
        reasoning = _integer(payload.get("reasoning_tokens"))
    classified_prompt = cache_hit + cache_miss
    return NormalizedUsage(
        input_tokens=max(prompt_tokens - classified_prompt, 0),
        output_tokens=max(completion_tokens - reasoning, 0),
        cache_hit_tokens=cache_hit,
        cache_miss_tokens=cache_miss,
        reasoning_tokens=reasoning,
    )


class HttpProviderClient:
    def __init__(self, cipher: SecretCipher) -> None:
        self.cipher = cipher

    def call(
        self,
        route: ProviderRoute,
        payload: dict[str, object],
    ) -> ProviderResponse:
        request_payload = dict(payload)
        request_payload["model"] = route.provider_model
        api_key = self.cipher.decrypt(
            route.api_key_ciphertext,
            purpose=f"provider-route:{route.model_id}:{route.priority}",
        )
        try:
            response = httpx.post(
                _chat_completions_endpoint(route),
                json=request_payload,
                headers={"Authorization": f"Bearer {api_key}"},
                timeout=route.timeout_seconds,
            )
        except httpx.HTTPError as exc:
            raise ProviderCallError(
                "provider_network_error",
                "模型渠道网络请求失败。",
                retryable=True,
            ) from exc
        response_payload = _json_object(response)
        usage = _usage_from_response(response_payload)
        if response.status_code >= 400:
            raise ProviderCallError(
                f"provider_http_{response.status_code}",
                "模型渠道返回错误。",
                retryable=response.status_code in {401, 403, 408, 409, 429}
                or response.status_code >= 500,
                usage=usage,
            )
        if usage is None:
            raise ProviderCallError(
                "provider_usage_missing",
                "模型渠道未返回可信Token用量。",
                retryable=True,
            )
        return ProviderResponse(payload=response_payload, usage=usage)


def _chat_completions_endpoint(route: ProviderRoute) -> str:
    base = route.base_url.rstrip("/")
    if route.provider_type == "deepseek":
        return base + "/chat/completions"
    if base.endswith("/v1"):
        return base + "/chat/completions"
    return base + "/v1/chat/completions"


def _json_object(response: httpx.Response) -> dict[str, object]:
    try:
        payload = response.json()
    except ValueError as exc:
        raise ProviderCallError(
            "provider_invalid_json",
            "模型渠道未返回有效JSON。",
            retryable=True,
        ) from exc
    if not isinstance(payload, dict):
        raise ProviderCallError(
            "provider_invalid_json",
            "模型渠道返回的JSON结构无效。",
            retryable=True,
        )
    return payload


def _usage_from_response(payload: dict[str, object]) -> NormalizedUsage | None:
    raw_usage = payload.get("usage")
    if not isinstance(raw_usage, dict):
        return None
    return normalize_openai_usage(raw_usage)


def _integer(value: object) -> int:
    if not isinstance(value, (int, float, str)):
        return 0
    try:
        return max(int(value or 0), 0)
    except (TypeError, ValueError):
        return 0
