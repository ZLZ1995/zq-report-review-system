"""S12 浏览器面板控制器：用户主动打开/隐藏浏览器。

- 可见性按 session 隔离（切换会话不串浏览器任务）；
- 隐藏只是面板不可见，不结束后台浏览器任务（端口协议仅 show/hide）；
- OA 不写死为首页：无地址打开落在 about:blank；
- 真实 PySide 面板端口在 S14 接线。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class BrowserViewModel:
    session_id: str
    visible: bool
    url: str | None


class BrowserPanelPort(Protocol):
    def show(self, session_id: str, url: str) -> None: ...
    def hide(self, session_id: str) -> None: ...


class BrowserController:
    def __init__(self, port: BrowserPanelPort) -> None:
        self._port = port
        self._state: dict[str, dict] = {}

    def open_browser(self, session_id: str, url: str | None = None
                     ) -> BrowserViewModel:
        url = url or 'about:blank'
        self._state[session_id] = {'visible': True, 'url': url}
        self._port.show(session_id, url)
        return BrowserViewModel(session_id=session_id, visible=True, url=url)

    def hide_browser(self, session_id: str) -> BrowserViewModel:
        entry = self._state.setdefault(
            session_id, {'visible': False, 'url': None})
        entry['visible'] = False
        self._port.hide(session_id)
        return BrowserViewModel(session_id=session_id, visible=False,
                                url=entry['url'])

    def view(self, session_id: str) -> BrowserViewModel:
        entry = self._state.get(session_id)
        if entry is None:
            return BrowserViewModel(session_id=session_id, visible=False,
                                    url=None)
        return BrowserViewModel(session_id=session_id,
                                visible=entry['visible'], url=entry['url'])
