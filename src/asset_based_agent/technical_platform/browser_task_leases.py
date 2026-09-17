"""GUI-thread tab ownership, independent of website/business-action consent.

Only native controllers may register pages or acquire leases. Model arguments
cannot construct authority. Cancellation is rechecked before every operation.
"""
from dataclasses import dataclass
from uuid import uuid4

from PySide6.QtWebEngineCore import QWebEnginePage

from .browser_profile import BrowserSession
from .browser_task_permissions import BrowserTaskPermissions
from .task_manager import ManagedWorker, TaskBinding, TaskManager


@dataclass(frozen=True, repr=False)
class TabLease:
    tab_id: str
    binding: TaskBinding
    worker: ManagedWorker


class BrowserTaskLeases:
    def __init__(self, session: BrowserSession, manager: TaskManager | None):
        self.session, self.manager = session, manager
        self.permissions = BrowserTaskPermissions()
        self._pages: dict[str, QWebEnginePage] = {}
        self._leases: dict[str, TabLease] = {}
        self._closed = False

    def register(self, page: QWebEnginePage) -> str:
        if self._closed or not self.session.owns_page(page):
            raise PermissionError('Page unavailable')
        existing = self.tab_id(page)
        if existing is not None:
            return existing
        key = uuid4().hex
        self._pages[key] = page
        return key

    def tab_id(self, page: QWebEnginePage) -> str | None:
        return next((key for key, value in self._pages.items() if value is page), None)

    def _active(self, binding: TaskBinding, worker: ManagedWorker) -> bool:
        return (not self._closed and binding.owner == self.session.owner and self.manager is not None
                and self.manager.owns(binding, worker) and worker.isRunning() and not worker.cancel.is_set())

    def acquire(self, page: QWebEnginePage, binding: TaskBinding, worker: ManagedWorker, *,
                confirmed: bool) -> TabLease:
        key = self.tab_id(page)
        if (confirmed is not True or key is None or not self.session.owns_page(page)
                or not self._active(binding, worker)):
            raise PermissionError('Browser task unavailable or unconfirmed')
        existing = self._leases.get(key)
        if existing is not None and self.valid(existing):
            raise PermissionError('Tab already controlled by a task')
        self.permissions.revoke_tab(key)
        lease = TabLease(key, binding, worker)
        self._leases[key] = lease
        return lease

    def valid(self, lease: TabLease) -> bool:
        if not isinstance(lease, TabLease) or self._leases.get(lease.tab_id) is not lease:
            return False
        page = self._pages.get(lease.tab_id)
        active = self._active(lease.binding, lease.worker) and self.session.owns_page(page)
        if not active:
            self.release(lease)
        return active

    def release(self, lease: TabLease) -> None:
        if self._leases.get(lease.tab_id) is lease:
            del self._leases[lease.tab_id]
            self.permissions.revoke_tab(lease.tab_id)

    def takeover(self, page: QWebEnginePage) -> bool:
        key = self.tab_id(page)
        if key is None:
            return False
        self.permissions.revoke_tab(key)
        lease = self._leases.pop(key, None)
        # Only explicit manual takeover removes a task's navigation restriction.
        # Cancellation alone must not let an in-flight redirect leave its scope.
        if hasattr(page, 'take_over_navigation'):
            page.take_over_navigation()
        return lease is not None

    def unregister(self, page: QWebEnginePage) -> None:
        key = self.tab_id(page)
        self.takeover(page)
        if key is not None:
            del self._pages[key]

    def close(self) -> None:
        self._closed = True
        self._leases.clear()
        self._pages.clear()
        self.permissions.close()
