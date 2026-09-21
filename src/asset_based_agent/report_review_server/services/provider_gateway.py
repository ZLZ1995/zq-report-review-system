"""Provider calls and normalized Token usage."""

from __future__ import annotations

import json
from collections.abc import Iterable, Iterator
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
        if any(type(value) is not int or value < 0 for value in self.values()):
            raise ValueError("Token usage must be nonnegative integers")

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
    cache_hit = _integer(payload.get("prompt_cache_hit_tokens", 0))
    cache_miss = _integer(payload.get("prompt_cache_miss_tokens", 0))
    details = payload.get("completion_tokens_details")
    reasoning = 0
    if details is not None:
        if not isinstance(details, dict):
            raise ValueError("Invalid completion token details")
        reasoning = _integer(details.get("reasoning_tokens", 0))
    if "reasoning_tokens" in payload:
        direct = _integer(payload["reasoning_tokens"])
        if isinstance(details, dict) and "reasoning_tokens" in details and direct != reasoning:
            raise ValueError("Conflicting reasoning token counts")
        reasoning = direct
    classified_prompt = cache_hit + cache_miss
    if classified_prompt > prompt_tokens or reasoning > completion_tokens:
        raise ValueError("Token partitions exceed totals")
    if "total_tokens" in payload and _integer(payload["total_tokens"]) != prompt_tokens + completion_tokens:
        raise ValueError("Token totals do not reconcile")
    return NormalizedUsage(
        input_tokens=prompt_tokens - classified_prompt,
        output_tokens=completion_tokens - reasoning,
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
                retryable=False,
            )
        return ProviderResponse(payload=response_payload, usage=usage)

    def stream(
        self,
        route: ProviderRoute,
        payload: dict[str, object],
    ) -> Iterator[dict[str, object]]:
        """OpenAI 兼容 SSE 流；产出 iter_openai_stream_events 归一化事件。"""
        request_payload = dict(payload)
        request_payload["model"] = route.provider_model
        request_payload["stream"] = True
        request_payload["stream_options"] = {"include_usage": True}
        api_key = self.cipher.decrypt(
            route.api_key_ciphertext,
            purpose=f"provider-route:{route.model_id}:{route.priority}",
        )
        try:
            with httpx.stream(
                "POST",
                _chat_completions_endpoint(route),
                json=request_payload,
                headers={"Authorization": f"Bearer {api_key}"},
                timeout=route.timeout_seconds,
            ) as response:
                if response.status_code >= 400:
                    raise ProviderCallError(
                        f"provider_http_{response.status_code}",
                        "模型渠道返回错误。",
                        retryable=response.status_code in {401, 403, 408, 409, 429}
                        or response.status_code >= 500,
                    )
                yield from iter_openai_stream_events(response.iter_lines())
        except httpx.HTTPError as exc:
            raise ProviderCallError(
                "provider_network_error",
                "模型渠道网络请求失败。",
                retryable=True,
            ) from exc


def iter_openai_stream_events(
    lines: Iterable[str],
) -> Iterator[dict[str, object]]:
    """把 OpenAI 兼容 SSE 行流归一化为内部流事件。

    产出 kind ∈ {message_start, text_delta, tool_call_delta,
    tool_call_complete, usage, message_complete}。
    """
    started = False
    tool_buffers: dict[int, dict[str, object]] = {}
    finish_reason: str | None = None
    usage: dict[str, int] | None = None
    for raw in lines:
        line = raw.strip()
        if not line.startswith("data:"):
            continue
        data = line[5:].strip()
        if data == "[DONE]":
            break
        try:
            chunk = json.loads(data)
        except ValueError as exc:
            raise ProviderCallError(
                "provider_invalid_json",
                "模型渠道流式帧不是有效JSON。",
                retryable=True,
            ) from exc
        if not isinstance(chunk, dict):
            continue
        raw_usage = chunk.get("usage")
        if isinstance(raw_usage, dict) and raw_usage:
            details = raw_usage.get("completion_tokens_details") or {}
            usage = {
                "input_tokens": int(raw_usage.get("prompt_tokens") or 0),
                "output_tokens": int(raw_usage.get("completion_tokens") or 0),
                "cache_hit_tokens": int(
                    raw_usage.get("prompt_cache_hit_tokens") or 0),
                "cache_miss_tokens": int(
                    raw_usage.get("prompt_cache_miss_tokens") or 0),
                "reasoning_tokens": int(details.get("reasoning_tokens") or 0),
            }
        for choice in chunk.get("choices") or []:
            delta = choice.get("delta") or {}
            if not started:
                started = True
                yield {"kind": "message_start", "data": {}}
            content = delta.get("content")
            if content:
                yield {"kind": "text_delta", "data": {"text": content}}
            for tool_call in delta.get("tool_calls") or []:
                index = int(tool_call.get("index") or 0)
                buffer = tool_buffers.setdefault(
                    index, {"id": None, "name": "", "fragments": []})
                if tool_call.get("id"):
                    buffer["id"] = tool_call["id"]
                function = tool_call.get("function") or {}
                if function.get("name"):
                    buffer["name"] = function["name"]
                fragment = function.get("arguments") or ""
                buffer["fragments"].append(fragment)
                yield {"kind": "tool_call_delta", "data": {
                    "index": index, "name": buffer["name"],
                    "arguments_fragment": fragment,
                }}
            if choice.get("finish_reason"):
                finish_reason = str(choice["finish_reason"])
    if tool_buffers:
        for index in sorted(tool_buffers):
            buffer = tool_buffers[index]
            try:
                arguments = json.loads("".join(buffer["fragments"]) or "{}")
            except ValueError:
                arguments = None
            yield {"kind": "tool_call_complete", "data": {
                "id": buffer["id"] or f"call-{index}",
                "name": buffer["name"], "arguments": arguments,
            }}
    if usage is not None:
        yield {"kind": "usage", "data": usage}
    yield {"kind": "message_complete", "data": {"finish_reason": finish_reason}}


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
    try:
        return normalize_openai_usage(raw_usage)
    except ValueError as exc:
        # The upstream may have charged already; do not create another attempt
        # from untrustworthy accounting data or return a zero-usage success.
        raise ProviderCallError(
            "provider_usage_invalid", "模型渠道返回的Token用量无法核验。", retryable=False
        ) from exc


def _integer(value: object) -> int:
    if type(value) is not int or value < 0:
        raise ValueError("Token count must be a nonnegative integer")
    return value
