"""GUI-thread download lifecycle, with explicit destination consent."""
import logging
import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QObject, QTimer, QUrl, Signal
from PySide6.QtWebEngineCore import QWebEngineDownloadRequest, QWebEnginePage

from .browser_downloads import DownloadTarget
from .browser_policy import credential_origin, navigation_url
from .browser_profile import BrowserSession


@dataclass
class DownloadRecord:
    target: DownloadTarget
    status: str = 'running'
    received: int = 0
    total: int = -1
    cleanup_pending: bool = False
    task_id: str | None = None


@dataclass(frozen=True)
class TaskDownloadPermission:
    """Native-only callbacks; never construct from model or webpage data."""
    task_id: str
    active: Callable[[], bool]
    admit: Callable[[str, Path], bool]
    finished: Callable[[str, DownloadRecord | None], None]
    allow_blob: bool = False


@dataclass
class _TaskDownload:
    page: QWebEnginePage
    owner: object
    permission: TaskDownloadPermission
    expires: float


class BrowserDownloads(QObject):
    changed = Signal(int)
    rejected = Signal(str)

    def __init__(self, session: BrowserSession, choose: Callable[[str], Path | None]):
        super().__init__()
        if session.profile is None or session.download_journal is None:
            raise ValueError('Browser session is closed')
        self.session = session
        self.profile = session.profile
        self.journal = session.download_journal
        self.choose = choose
        self.records: dict[int, DownloadRecord] = {}
        self._active: dict[int, QWebEngineDownloadRequest] = {}
        self._closed = False
        self._armed: dict[int, _TaskDownload] = {}
        self._tasks: dict[int, _TaskDownload] = {}
        self._blob_sources: dict[int, tuple[QWebEnginePage, str]] = {}
        self.timer = QTimer(self)
        self.timer.setInterval(100)
        self.timer.timeout.connect(self.check_tasks)
        self.profile.downloadRequested.connect(self.request)

    def _valid_task(self, task: _TaskDownload) -> bool:
        try:
            return (not self._closed and self.session.owns_page(task.page)
                    and getattr(task.page, '_task_navigation_owner', None) is task.owner
                    and task.permission.active() is True)
        except (ValueError, OSError, RuntimeError, sqlite3.Error):
            return False

    @staticmethod
    def _notify(task: _TaskDownload, status: str, record: DownloadRecord | None = None) -> None:
        try:
            task.permission.finished(status, record)
        except Exception:  # noqa: BLE001 - native callback boundary, never repeat a download
            logging.getLogger(__name__).warning('Native download result callback failed; no retry scheduled')

    def arm_task(self, page, permission: TaskDownloadPermission) -> None:
        owner = getattr(page, '_task_navigation_owner', None)
        if (not isinstance(permission, TaskDownloadPermission) or not permission.task_id
                or owner is None or id(page) in self._armed
                or getattr(getattr(owner, 'binding', None), 'task_id', None) != permission.task_id
                or any(task.page is page for task in self._tasks.values())):
            raise PermissionError('Download task is unavailable or already pending')
        task = _TaskDownload(page, owner, permission, time.monotonic() + 45)
        if not self._valid_task(task):
            raise PermissionError('Download task is inactive')
        self._armed[id(page)] = task
        if QCoreApplication.instance() is not None:
            self.timer.start()

    def disarm_task(self, page, permission: TaskDownloadPermission) -> None:
        task = self._armed.get(id(page))
        if task is not None and task.permission is permission:
            self._armed.pop(id(page))
            self._notify(task, 'cancelled')
        for key, task in list(self._tasks.items()):
            if task.page is page and task.permission is permission:
                self.cancel(key)

    def check_tasks(self) -> None:
        for page_id, task in list(self._armed.items()):
            if not self._valid_task(task) or time.monotonic() > task.expires:
                self._armed.pop(page_id)
                self._notify(task, 'cancelled')
        for key in list(self._tasks):
            self._update(key)
        for key in list(self._blob_sources):
            if key not in self._tasks:
                self._update(key)
        if not self._armed and not self._tasks and not self._blob_sources:
            self.timer.stop()

    def _same_blob_page(self, page, source: str) -> bool:
        try:
            return (not self._closed and self.session.owns_page(page)
                    and not page.isLoading() and page.url().toString() == source)
        except (AttributeError, RuntimeError):
            return False

    def request(self, item: QWebEngineDownloadRequest) -> None:
        page = item.page()
        task = self._armed.pop(id(page), None)
        if (self._closed or not self.session.owns_page(item.page())
                or item.isSavePageDownload()
                or (task is None and getattr(page, '_task_navigation_owner', None) is not None)
                or (task is not None and (not self._valid_task(task) or time.monotonic() > task.expires))):
            item.cancel()
            if task is not None:
                self._notify(task, 'rejected')
            return
        target = None
        blob_source = None
        try:
            raw_url = item.url().toString()
            if raw_url.startswith('blob:'):
                if task is not None and not task.permission.allow_blob:
                    raise PermissionError('Task has no generated-download permission')
                blob_source = page.url().toString()
                inner = navigation_url(raw_url[5:])
                if (credential_origin(raw_url[5:]) != credential_origin(blob_source)
                        or inner.path() in {'', '/'} or inner.hasQuery() or inner.hasFragment()
                        or not self._same_blob_page(page, blob_source)):
                    raise ValueError('Generated download has an untrusted source')
                url = QUrl(raw_url, QUrl.ParsingMode.StrictMode)
                if not url.isValid():
                    raise ValueError('Invalid generated download')
            else:
                url = navigation_url(raw_url)
                if url.scheme() not in {'http', 'https'}:
                    raise ValueError('Unsupported download URL')
            destination = self.choose(item.suggestedFileName())
            # A modal file picker can process shutdown/account-switch events.
            if destination is None or self._closed or not self.session.owns_page(item.page()):
                item.cancel()
                if task is not None:
                    self._notify(task, 'rejected')
                return
            if blob_source is not None and not self._same_blob_page(page, blob_source):
                raise PermissionError('Generated download page changed during confirmation')
            if task is not None and (not self._valid_task(task)
                    or task.permission.admit(url.toString(), destination) is not True
                    or not self._valid_task(task)):
                raise PermissionError('Download task changed or destination was not authorized')
            if task is None and getattr(page, '_task_navigation_owner', None) is not None:
                raise PermissionError('Page became task-owned during manual confirmation')
            target = DownloadTarget(destination)
            self.journal.track(target)
        except (OSError, ValueError, sqlite3.Error):
            item.cancel()
            if target is not None:
                # The request has not been accepted: Chromium cannot be writing.
                try:
                    target.discard()
                except (ValueError, OSError):
                    pass  # Retain uncertain content; never recurse or overwrite.
            self.rejected.emit('下载未开始：请选择非系统盘中未占用的安全文件路径。')
            if task is not None:
                self._notify(task, 'rejected')
            return
        key = item.id()
        self.records[key] = DownloadRecord(target, task_id=task.permission.task_id if task is not None else None)
        self._active[key] = item
        if blob_source is not None:
            self._blob_sources[key] = (page, blob_source)
            if QCoreApplication.instance() is not None:
                self.timer.start()
        if task is not None:
            self._tasks[key] = task
        item.setDownloadDirectory(str(target.stage))
        item.setDownloadFileName(target.partial.name)
        item.stateChanged.connect(lambda _state, key=key: self._update(key))
        item.receivedBytesChanged.connect(lambda key=key: self._update(key))
        item.totalBytesChanged.connect(lambda key=key: self._update(key))
        item.accept()
        self._update(key)

    def _update(self, key: int) -> None:
        item = self._active.get(key)
        if item is None:
            return
        record = self.records[key]
        record.received, record.total = item.receivedBytes(), item.totalBytes()
        state = item.state()
        states = QWebEngineDownloadRequest.DownloadState
        task = self._tasks.get(key)
        revoked = task is not None and not self._valid_task(task)
        blob = self._blob_sources.get(key)
        if blob is not None and not self._same_blob_page(*blob):
            revoked = True
        if revoked and state not in {states.DownloadCompleted, states.DownloadCancelled, states.DownloadInterrupted}:
            item.cancel()
            return
        if state in {states.DownloadCompleted, states.DownloadCancelled, states.DownloadInterrupted}:
            self._active.pop(key)
            self._tasks.pop(key, None)
            self._blob_sources.pop(key, None)
            if state == states.DownloadCompleted and not self._closed and not revoked:
                try:
                    record.target.publish()
                    record.status = 'completed'
                    record.cleanup_pending = record.target.cleanup_pending
                    if not record.cleanup_pending:
                        try:
                            self.journal.forget(record.target.stage)
                        except (ValueError, OSError, sqlite3.Error):
                            record.cleanup_pending = True
                except (OSError, ValueError):
                    record.status = 'failed'
                    record.cleanup_pending = True
            else:
                record.status = 'cancelled' if self._closed or revoked or state == states.DownloadCancelled else 'failed'
                # Qt terminal signals are not a Chromium filesystem barrier.
                # Early removal races background creation/writes; retain the
                # isolated stage for cold recovery after profile shutdown.
                record.cleanup_pending = True
            if task is not None:
                self._notify(task, record.status, record)
        self.changed.emit(key)

    def cancel(self, key: int) -> None:
        item = self._active.get(key)
        if item is not None:
            item.cancel()
            self._update(key)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self.timer.stop()
        armed, self._armed = self._armed, {}
        for task in armed.values():
            self._notify(task, 'cancelled')
        self.profile.downloadRequested.disconnect(self.request)
        for key in list(self._active):
            self.cancel(key)
