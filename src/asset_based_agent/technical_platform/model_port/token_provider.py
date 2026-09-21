"""Access token 持有与 single-flight 刷新。

并发请求同时遇到 401 时，只有第一个协程执行真实 refresh，其余协程
在锁内发现 token 已变化后直接复用——双进程/多请求不互相注销、不重复
刷新（服务端另有 refresh 宽容窗口兜底跨进程场景）。
"""
from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable


class TokenManager:
    def __init__(self, *, access_token: str,
                 refresh_fn: Callable[[], Awaitable[str]]) -> None:
        self._access_token = access_token
        self._refresh_fn = refresh_fn
        self._lock = asyncio.Lock()

    @property
    def access_token(self) -> str:
        return self._access_token

    async def refresh(self, *, stale_token: str) -> str:
        """single-flight：若锁内 token 已不再是 stale_token，直接复用。"""
        async with self._lock:
            if self._access_token != stale_token:
                return self._access_token
            self._access_token = await self._refresh_fn()
            return self._access_token
