"""Task-bound native navigation with scoped redirects and bounded completion.

can_navigate must be a synchronous native policy, not a model decision or UI
prompt. Loaded only means page loading finished, never business-task success.
"""
from collections.abc import Callable

from PySide6.QtCore import QObject, QTimer
from PySide6.QtWebEngineCore import QWebEnginePage

from .browser_page import BrowserPage
from .browser_policy import navigation_url
from .browser_task_leases import BrowserTaskLeases, TabLease


class BrowserNavigation(QObject):
    def __init__(self, leases: BrowserTaskLeases, page: BrowserPage, lease: TabLease, *,
                 can_navigate: Callable[[TabLease, str], bool]):
        if not leases.valid(lease) or leases.tab_id(page) != lease.tab_id:
            raise PermissionError('Navigation page does not belong to task')
        super().__init__(page)
        self.leases, self.page, self.lease, self.policy = leases, page, lease, can_navigate
        self.closed = False
        self.denied = False
        self.pending: Callable[[str], None] | None = None
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(30000)
        self.timer.timeout.connect(self.cancel)
        page.set_task_navigation_guard(lease, self._guard)
        page.loadFinished.connect(self._finished)

    def _allowed(self, url: str) -> bool:
        try:
            navigation_url(url)
            return (not self.closed and self.leases.valid(self.lease)
                    and self.leases.session.owns_page(self.page)
                    and self.policy(self.lease, url) is True
                    and self.leases.valid(self.lease))
        except (ValueError, OSError, RuntimeError):
            return False

    def _guard(self, url: str) -> bool:
        allowed = self._allowed(url)
        if not allowed:
            self.denied = True
        return allowed

    def navigate(self, url: str, callback: Callable[[str], None]) -> None:
        if self.pending is not None or not self._allowed(url) or self.page.isLoading():
            callback('rejected')
            return
        self.denied = False
        self.pending = callback
        self.timer.start()
        self.page.setUrl(navigation_url(url))

    def _complete(self, result: str) -> None:
        callback, self.pending = self.pending, None
        self.timer.stop()
        if callback is not None:
            callback(result)

    def _finished(self, ok: bool) -> None:
        if self.pending is None:
            return
        if not self.leases.valid(self.lease):
            self._complete('unknown')
        elif self.denied:
            self._complete('rejected')
        elif ok and self._allowed(self.page.url().toString()):
            self._complete('loaded')
        else:
            self._complete('failed')

    def cancel(self) -> None:
        if self.pending is not None:
            # Take the callback before stop can cause a synchronous load signal.
            callback, self.pending = self.pending, None
            self.timer.stop()
            if self.leases.session.owns_page(self.page):
                self.page.triggerAction(QWebEnginePage.WebAction.Stop)
            callback('unknown')

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        self.cancel()
        if self.leases.session.owns_page(self.page):
            self.page.loadFinished.disconnect(self._finished)
            self.page.clear_task_navigation_guard(self.lease)
