"""ServerModelPort：经服务端流式端点接入模型的 ModelPort 实现。

不变量（计划书 S06）：
- 客户端不持有任何供应商 API Key（只有平台 access token）；
- 请求负载只含 role/content 文本消息与工具 schema——不含文件路径字段
  和二进制负载；
- 每个请求携带幂等编号（client_request_id），重试不重复计费；
- 401 → single-flight refresh → 重试一次；
- 取消主动关闭底层 HTTP 流，服务端据此留下 disconnected 对账状态；
- 所有失败归类为稳定 AgentError 子类，不裸抛 httpx 异常。
"""
from __future__ import annotations

import asyncio
import contextlib
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING

import httpx

from ..agent_core.contracts import ModelEvent, ToolDescriptor
from ..agent_core.errors import (
    AgentCancelled,
    InvalidRequest,
    ModelAuthFailed,
    ModelBalanceInsufficient,
    ModelBillingReconciliation,
    ModelProtocolError,
    ModelTimeout,
    ServerCapabilityUnavailable,
)
from .message_mapping import entries_to_wire_messages
from .sse import iter_sse_events

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from ..agent_core.cancellation import CancelToken
    from ..agent_core.contracts import ModelRequest
    from .token_provider import TokenManager

_PROTOCOL_VERSION = 1
_RESERVED_SAMPLING_KEYS = frozenset({'messages', 'tools'})

# 服务端结构化错误码 → 稳定客户端错误类（未知码一律 ModelProtocolError）
_ERROR_MAP = {
    'provider_auth_failed': ModelAuthFailed,
    'session_revoked': ModelAuthFailed,
    'token_expired': ModelAuthFailed,
    'authentication_required': ModelAuthFailed,
    'provider_timeout': ModelTimeout,
    'provider_network_error': ModelTimeout,
    'provider_unavailable': ModelTimeout,
    'insufficient_balance': ModelBalanceInsufficient,
    'billing_reconciliation_required': ModelBillingReconciliation,
}

_STREAM_EVENT_KINDS = frozenset({
    'message_start', 'text_delta', 'thinking_delta', 'tool_call_delta',
    'tool_call_complete', 'message_complete',
})


class ServerModelPort:
    def __init__(self, *, base_url: str, token_manager: TokenManager,
                 client: httpx.AsyncClient | None = None,
                 client_version: str = '', timeout: float = 120.0,
                 balance_path: str = '/api/v1/account/balance',
                 stream_path: str = '/api/v1/agent/completions/stream',
                 require_stream_capability: bool = False) -> None:
        self.base_url = base_url.rstrip('/')
        self.token_manager = token_manager
        self.client = client or httpx.AsyncClient(timeout=timeout)
        self.client_version = client_version
        self.balance_path = balance_path
        self.stream_path = stream_path
        self.require_stream_capability = require_stream_capability
        self._stream_capability_checked = False
        self.last_receipt: dict | None = None

    def _endpoint(self, path: str) -> str:
        """Join an API path without duplicating the ``/api/v1`` prefix.

        The authentication client exposes the versioned service URL
        (``.../api/v1``), while the model port owns versioned endpoint paths.
        The previous direct concatenation therefore queried
        ``.../api/v1/api/v1/capabilities`` in the packaged client and surfaced
        a misleading ``server.capability_missing`` error.
        """
        prefix = '/api/v1'
        if self.base_url.endswith(prefix) and path.startswith(prefix + '/'):
            return self.base_url + path[len(prefix):]
        return self.base_url + path

    # ------------------------------------------------------------- 入口

    async def stream(
        self,
        request: ModelRequest,
        cancel: CancelToken,
    ) -> AsyncIterator[ModelEvent]:
        cancel.raise_if_cancelled()
        if not request.request_id:
            raise InvalidRequest('模型请求缺少幂等编号（request_id）')
        payload = self._build_payload(request)
        await self._preflight_balance(cancel)
        response = await self._open_stream(payload, cancel)
        pending_usage: dict | None = None
        try:
            lines = self._cancellable_lines(response, cancel)
            async for kind, data in iter_sse_events(lines):
                if kind == 'error':
                    raise _map_error(data.get('code'), data.get('message'))
                if kind == 'usage':
                    pending_usage = dict(data)
                    continue
                if kind == 'receipt':
                    # 计费回执并入 usage：turn.usage 直接持久化可对账信息
                    self.last_receipt = dict(data)
                    merged = dict(pending_usage or {})
                    merged.update({
                        'charged_amount': str(data.get('charged_amount', '')),
                        'billing_request_id': str(
                            data.get('billing_request_id', '')),
                        'replayed': bool(data.get('replayed')),
                    })
                    yield ModelEvent('usage', merged)
                    pending_usage = None
                    continue
                if kind in _STREAM_EVENT_KINDS:
                    yield ModelEvent(kind, data)
                # 未知事件类型忽略（向前兼容未来协议版本）
            if pending_usage is not None:
                yield ModelEvent('usage', pending_usage)
        finally:
            with contextlib.suppress(Exception):
                await response.aclose()

    # ----------------------------------------------------------- 预检

    async def _preflight_balance(self, cancel: CancelToken) -> None:
        """余额预检：权威拦截余额不足；预检本身失败（网络等）不阻断。"""
        try:
            response = await self._get_with_auth_retry(
                self._endpoint(self.balance_path), cancel)
        except (httpx.RequestError, ModelTimeout):
            return  # 服务端计费仍是权威，预检失败降级为建议性
        try:
            data = response.json()
            balance = Decimal(str(data.get('balance', '')))
        except (ValueError, TypeError, InvalidOperation):
            return
        if balance <= 0:
            raise ModelBalanceInsufficient('账户余额不足，无法发起模型请求')

    # ----------------------------------------------------------- 传输

    async def _open_stream(self, payload: dict,
                           cancel: CancelToken) -> httpx.Response:
        if self.require_stream_capability and not self._stream_capability_checked:
            await self._ensure_stream_capability(cancel)
        used = self.token_manager.access_token
        response = await self._post_stream(payload, used, cancel)
        if response.status_code == 401:
            await response.aclose()
            token = await self.token_manager.refresh(stale_token=used)
            response = await self._post_stream(payload, token, cancel)
        if response.status_code != 200:
            try:
                await response.aread()
                code, message = _error_envelope(response)
            finally:
                await response.aclose()
            if response.status_code == 404:
                raise ServerCapabilityUnavailable(
                    '服务端尚未部署新 Agent 流式接口，请先升级服务端。')
            raise _map_error(code, message or f'HTTP {response.status_code}')
        return response

    async def _ensure_stream_capability(self, cancel: CancelToken) -> None:
        response = await self._get_with_auth_retry(
            self._endpoint('/api/v1/capabilities'), cancel)
        if response.status_code == 404:
            raise ServerCapabilityUnavailable(
                '服务端未提供能力协商接口，请先升级服务端。')
        if response.status_code != 200:
            with contextlib.suppress(Exception):
                await response.aclose()
            raise ServerCapabilityUnavailable(
                '无法确认服务端是否支持新 Agent，请先升级服务端。')
        try:
            data = response.json()
            capabilities = data.get('capabilities', {})
            supported = (
                isinstance(data, dict)
                and data.get('schema_version') == 1
                and data.get('protocol_version') == 1
                and isinstance(capabilities, dict)
                and capabilities.get('agent_completion_stream') == 1
            )
        except (TypeError, ValueError):
            supported = False
        finally:
            with contextlib.suppress(Exception):
                await response.aclose()
        if not supported:
            raise ServerCapabilityUnavailable(
                '服务端尚未部署新 Agent 流式接口，请先升级服务端。')
        self._stream_capability_checked = True

    async def _post_stream(self, payload: dict, token: str,
                           cancel: CancelToken) -> httpx.Response:
        request = self.client.build_request(
            'POST', self._endpoint(self.stream_path), json=payload,
            headers={'Authorization': f'Bearer {token}'})
        try:
            return await _race_transport(self.client.send(request, stream=True),
                                         cancel)
        except httpx.RequestError as exc:
            raise ModelTimeout(f'无法连接模型服务: {exc.__class__.__name__}') from exc

    async def _get_with_auth_retry(self, url: str,
                                   cancel: CancelToken) -> httpx.Response:
        used = self.token_manager.access_token
        response = await self._get(url, used, cancel)
        if response.status_code == 401:
            token = await self.token_manager.refresh(stale_token=used)
            response = await self._get(url, token, cancel)
        return response

    async def _get(self, url: str, token: str,
                   cancel: CancelToken) -> httpx.Response:
        request = self.client.build_request(
            'GET', url, headers={'Authorization': f'Bearer {token}'})
        return await _race_transport(self.client.send(request), cancel)

    async def _cancellable_lines(self, response: httpx.Response,
                                 cancel: CancelToken) -> AsyncIterator[str]:
        iterator = response.aiter_lines()
        while True:
            task = asyncio.ensure_future(iterator.__anext__())
            watch = asyncio.ensure_future(cancel.wait())
            try:
                done, _pending = await asyncio.wait(
                    {task, watch}, return_when=asyncio.FIRST_COMPLETED)
                if watch in done and not task.done():
                    task.cancel()  # 关闭底层读取 → 连接释放 → 服务端对账
                    with contextlib.suppress(asyncio.CancelledError,
                                             StopAsyncIteration):
                        await task
                    raise AgentCancelled('操作已取消')
                try:
                    yield task.result()
                except StopAsyncIteration:
                    return
            finally:
                watch.cancel()
                await asyncio.gather(watch, return_exceptions=True)

    # ----------------------------------------------------------- 负载

    def _build_payload(self, request: ModelRequest) -> dict:
        sampling = {key: value
                    for key, value in (request.sampling or {}).items()
                    if key not in _RESERVED_SAMPLING_KEYS}
        return {
            'protocol_version': request.protocol_version or _PROTOCOL_VERSION,
            'client_version': request.client_version or self.client_version,
            'model_id': request.model_id,
            'client_request_id': request.request_id,
            'messages': entries_to_wire_messages(request.messages),
            'tools': [_wire_tool(tool) for tool in request.tools],
            'sampling': sampling,
        }


def _wire_tool(tool) -> dict:
    if isinstance(tool, ToolDescriptor):
        return {'name': tool.name, 'description': tool.description,
                'input_schema': tool.input_schema}
    return {'name': tool['name'], 'description': tool.get('description', ''),
            'input_schema': tool.get('input_schema', {})}


def _error_envelope(response: httpx.Response) -> tuple[str | None, str | None]:
    try:
        data = response.json()
    except ValueError:
        return None, None
    if not isinstance(data, dict) or not isinstance(data.get('error'), dict):
        return None, None
    error = data['error']
    return error.get('code'), error.get('message')


def _map_error(code, message):
    cls = _ERROR_MAP.get(str(code or ''), ModelProtocolError)
    return cls(str(message or code or '模型请求失败'))


async def _race_transport(awaitable, cancel: CancelToken):
    """传输 await 与取消竞速；取消时取消传输任务以释放底层连接。"""
    task = asyncio.ensure_future(awaitable)
    watch = asyncio.ensure_future(cancel.wait())
    try:
        done, _pending = await asyncio.wait(
            {task, watch}, return_when=asyncio.FIRST_COMPLETED)
        if watch in done and not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
            raise AgentCancelled('操作已取消')
        return await task
    finally:
        watch.cancel()
        await asyncio.gather(watch, return_exceptions=True)
