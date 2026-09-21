"""Cooperative cancellation token for agent operations.

cancel() 可能来自任意线程；wait() 让事件循环内的 await 点可以与
取消竞速（S05 late-result barrier 的前提）。
"""
import asyncio
from threading import Event

from .errors import AgentCancelled


class CancelToken:
    def __init__(self):
        self._event = Event()
        self._async_event = None
        self._loop = None

    def cancel(self):
        self._event.set()
        if self._async_event is not None and self._loop is not None:
            self._loop.call_soon_threadsafe(self._async_event.set)

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()

    @property
    def threading_event(self) -> Event:
        """供同步业务执行链（threading.Event 语义）协作式取消使用。"""
        return self._event

    def raise_if_cancelled(self):
        if self._event.is_set():
            raise AgentCancelled('操作已取消')

    async def wait(self):
        """挂起直到取消；与流式 await 点竞速使用。"""
        if self._async_event is None:
            self._loop = asyncio.get_running_loop()
            self._async_event = asyncio.Event()
            if self._event.is_set():
                self._async_event.set()
        await self._async_event.wait()
