"""Explicit browser storage ownership; never use Qt's global default profile."""
from __future__ import annotations

import atexit
import os
import sqlite3
from contextlib import ExitStack
from hashlib import sha256

import shiboken6
from PySide6.QtCore import QLockFile, QThread
from PySide6.QtWebEngineCore import (
    QWebEnginePage,
    QWebEngineProfile,
    QWebEngineSettings,
)
from PySide6.QtWidgets import QApplication
from typing_extensions import Self

from .browser_download_journal import DownloadJournal
from .browser_page import BrowserPage, BrowserRequestInterceptor
from .browser_policy import check_runtime_environment
from .storage_preferences import StoragePreferences

# Chromium can finish disk writes after its QObject is destroyed. Keep one
# profile and its data lease for the process lifetime; closing tabs is not a
# declaration that the directory is safe to migrate.
_profiles: dict[str, tuple[QWebEngineProfile, ExitStack]] = {}
_claimed: set[str] = set()


def _shutdown_profiles() -> None:
    from PySide6.QtWebEngineWidgets import QWebEngineView
    for profile, stack in _profiles.values():
        if shiboken6.isValid(profile):
            for page in profile.findChildren(QWebEnginePage):
                if not shiboken6.isValid(page):
                    continue
                view = QWebEngineView.forPage(page)
                if view is not None and shiboken6.isValid(view):
                    shiboken6.delete(view)
                if shiboken6.isValid(page):
                    shiboken6.delete(page)
            shiboken6.delete(profile)
        stack.close()
    _profiles.clear()
    _claimed.clear()


atexit.register(_shutdown_profiles)


class BrowserSession:
    """Own pages on the GUI thread, borrowing an application-lifetime profile.

    Close attached views before exiting this context. Hiding a panel must not
    close it. All pages must be created with new_page, never a default profile.
    """

    def __init__(self, preferences: StoragePreferences, owner: str, *, environment: str = 'production'):
        if environment not in {'production', 'test'}:
            raise ValueError('Unknown browser environment')
        self.preferences = preferences
        self.owner = owner
        self.environment = environment
        self.profile: QWebEngineProfile | None = None
        self.download_journal: DownloadJournal | None = None
        self._pages: list[QWebEnginePage] = []
        self._key: str | None = None

    @staticmethod
    def _check_thread() -> None:
        app = QApplication.instance()
        if app is None or QThread.currentThread() != app.thread():
            raise RuntimeError('Browser requires the application GUI thread')

    def __enter__(self) -> Self:
        self._check_thread()
        check_runtime_environment(os.environ)
        if self._key is not None:
            raise RuntimeError('Browser session is already open')
        stack = ExitStack()
        try:
            layout = stack.enter_context(self.preferences.use(self.owner))
            roots = (layout.browser_profiles / self.environment,
                     layout.cache / 'browser' / self.environment,
                     layout.downloads / 'browser' / self.environment)
            key = str(roots[0])
            self.download_journal = DownloadJournal(roots[0] / 'downloads.sqlite')
            if key in _claimed:
                raise RuntimeError('Browser profile is already in use')
            if key in _profiles:
                self.profile = _profiles[key][0]
                self._key = key
                _claimed.add(key)
                stack.close()
                return self
            for path in roots:
                if path.resolve() != path:
                    raise ValueError('Browser storage path is redirected')
                path.mkdir(parents=True, exist_ok=True)
            lock = QLockFile(str(roots[0] / 'profile.lock'))
            lock.setStaleLockTime(0)
            if not lock.tryLock(0):
                raise RuntimeError('Browser profile is already in use')
            stack.callback(lock.unlock)
            # Only the first acquisition in a new process may reclaim stages.
            # Cached profiles can still have Chromium IO threads in flight.
            try:
                self.download_journal.recover()
            except sqlite3.Error as exc:
                raise ValueError('Browser download journal unavailable') from exc
            name = 'zq-' + sha256(str(roots[0]).encode('utf-8')).hexdigest()
            profile = QWebEngineProfile(name)
            self.profile = profile
            profile.setPersistentStoragePath(str(roots[0]))
            profile.setCachePath(str(roots[1]))
            profile.setDownloadPath(str(roots[2]))
            profile.setPersistentCookiesPolicy(QWebEngineProfile.PersistentCookiesPolicy.AllowPersistentCookies)
            profile.setPersistentPermissionsPolicy(QWebEngineProfile.PersistentPermissionsPolicy.AskEveryTime)
            profile.setPushServiceEnabled(False)
            interceptor = BrowserRequestInterceptor(profile)
            profile.setUrlRequestInterceptor(interceptor)
            settings = profile.settings()
            for attribute in (
                QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls,
                QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls,
                QWebEngineSettings.WebAttribute.JavascriptCanAccessClipboard,
                QWebEngineSettings.WebAttribute.AllowRunningInsecureContent,
                QWebEngineSettings.WebAttribute.PluginsEnabled,
            ):
                settings.setAttribute(attribute, False)
            _profiles[key] = (profile, stack)
            _claimed.add(key)
            self._key = key
            return self
        except BaseException:
            if self.profile is not None:
                shiboken6.delete(self.profile)
                self.profile = None
            stack.close()
            raise

    def new_page(self) -> QWebEnginePage:
        self._check_thread()
        if self.profile is None:
            raise RuntimeError('Browser session is closed')
        page = BrowserPage(self.profile, self.profile)
        self._pages.append(page)
        return page

    def owns_page(self, page: QWebEnginePage | None) -> bool:
        return (self.profile is not None and page is not None
                and any(candidate is page and shiboken6.isValid(candidate) for candidate in self._pages))

    def close(self) -> None:
        self._check_thread()
        for page in self._pages:
            if shiboken6.isValid(page):
                shiboken6.delete(page)
        self._pages.clear()
        self.profile = None
        if self._key is not None:
            _claimed.discard(self._key)
            self._key = None

    def __exit__(self, *_exc) -> None:
        self.close()
