"""One-use page-bound login fill. No Agent-accessible secret or arbitrary eval API."""
import json
import sqlite3
import time
import weakref
from collections.abc import Callable
from dataclasses import dataclass
from uuid import uuid4

from PySide6.QtWebEngineCore import QWebEnginePage

from .browser_credential_vault import CredentialVault
from .browser_login_scripts import fill_script, probe_script
from .browser_policy import credential_origin
from .browser_profile import BrowserSession
from .browser_task_permissions import BrowserTaskPermissions, LoginPermit, LoginScope


@dataclass(frozen=True, repr=False)
class LoginTicket:
    nonce: str
    origin: str
    epoch: int
    expires: float


class TrustedLogin:
    def __init__(self, session: BrowserSession, page: QWebEnginePage, vault: CredentialVault, *,
                 tab_id: str | None = None,
                 task_permissions: BrowserTaskPermissions | None = None,
                 task_scope: Callable[[], LoginScope | None] | None = None):
        if not session.owns_page(page):
            raise ValueError('Login page does not belong to session')
        if (session.owner != vault.owner or session.environment != vault.environment
                or session.preferences is not vault.preferences):
            raise ValueError('Credential vault does not belong to session')
        self.session, self.vault = session, vault
        self._tab_id, self._permissions, self._task_scope = tab_id, task_permissions, task_scope
        self._page = weakref.ref(page)
        self._epoch = 0
        self._nonce: str | None = None
        self._ticket: LoginTicket | None = None
        self._closed = False
        page.loadStarted.connect(self.invalidate)
        page.urlChanged.connect(self.invalidate)
        page.renderProcessTerminated.connect(self.invalidate)

    def invalidate(self, *_args) -> None:
        self._epoch += 1
        self._nonce = None
        self._ticket = None
        if self._permissions is not None and self._tab_id is not None:
            self._permissions.revoke_tab(self._tab_id)

    @property
    def page_version(self) -> int:
        return self._epoch

    def _live(self) -> QWebEnginePage | None:
        page = self._page()
        return page if not self._closed and page is not None and self.session.owns_page(page) and not page.isLoading() else None

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self.invalidate()
        page = self._page()
        if page is not None and self.session.owns_page(page):
            for signal in (page.loadStarted, page.urlChanged, page.renderProcessTerminated):
                signal.disconnect(self.invalidate)

    def probe(self, callback: Callable[[LoginTicket | None], None]) -> None:
        self.invalidate()
        page = self._live()
        if page is None:
            callback(None)
            return
        try:
            origin = credential_origin(page.url().toString())
        except ValueError:
            callback(None)
            return
        nonce, epoch = uuid4().hex, self._epoch
        self._nonce = nonce

        def receive(raw):
            # Qt invokes callbacks even during page destruction; do not access
            # a native page until session ownership/liveness has been checked.
            current = self._live()
            ticket = None
            try:
                data = json.loads(raw) if isinstance(raw, str) else None
                if (current is not None and self._epoch == epoch and self._nonce == nonce
                        and isinstance(data, dict) and set(data) == {'ok', 'nonce', 'origin', 'action'}
                        and data['ok'] is True and data['nonce'] == nonce and data['origin'] == origin
                        and credential_origin(data['action']) == origin
                        and credential_origin(current.url().toString()) == origin):
                    ticket = LoginTicket(nonce, origin, epoch, time.monotonic()+60)
                    self._ticket = ticket
            except (ValueError, TypeError, RuntimeError):
                pass
            callback(ticket)

        try:
            page.runJavaScript(probe_script(nonce), 1, receive)
        except RuntimeError:
            self.invalidate()
            callback(None)

    def fill(self, ticket: LoginTicket, credential_id: str, *, confirmed: bool,
             callback: Callable[[bool], None]) -> None:
        self._fill(ticket, credential_id, confirmed=confirmed, agent=False, callback=callback)

    def fill_for_task(self, ticket: LoginTicket, permit: LoginPermit, *,
                      callback: Callable[[bool], None]) -> None:
        """Local dispatcher only: scope resolver must read authoritative native state.

        Never accept scope/active status from model arguments. This fills but does
        not submit; business actions need separate authorization.
        """
        allowed = False
        scope = None
        try:
            if self._task_scope is not None and self._permissions is not None:
                scope = self._task_scope()
                if scope is not None:
                    allowed = self._permissions.consume_login(permit, scope, task_active=True)
                    allowed = (allowed and not self._closed and scope.identity.owner == self.session.owner
                               and scope.environment == self.session.environment
                               and scope.tab_id == self._tab_id and scope.page_version == self._epoch
                               and isinstance(ticket, LoginTicket) and scope.origin == ticket.origin)
                elif self._tab_id is not None:
                    self._permissions.revoke_tab(self._tab_id)
        except (ValueError, OSError, RuntimeError):
            allowed = False
        if not allowed or scope is None:
            self._ticket = None
            callback(False)
            return
        def task_result(success: bool) -> None:
            # Already-dispatched DOM fill cannot be recalled; cancelled/replaced
            # tasks must not consume its late callback as success or submit next.
            try:
                success = (success and not self._closed and self._task_scope is not None
                           and self._task_scope() == scope)
            except (ValueError, OSError, RuntimeError):
                success = False
            callback(success)

        self._fill(ticket, scope.credential_id, confirmed=True, agent=True, callback=task_result)

    def _fill(self, ticket: LoginTicket, credential_id: str, *, confirmed: bool, agent: bool,
              callback: Callable[[bool], None]) -> None:
        current = self._live()
        valid = (isinstance(ticket, LoginTicket) and confirmed is True and ticket is self._ticket and current is not None
                 and ticket.epoch == self._epoch and time.monotonic() <= ticket.expires)
        self._ticket = None  # Consent/ticket is consumed even on a failed attempt.
        if not valid or current is None:
            callback(False)
            return
        try:
            if credential_origin(current.url().toString()) != ticket.origin:
                raise ValueError('Page changed')
            login = (self.vault._for_agent_fill(credential_id, ticket.origin) if agent
                     else self.vault._for_fill(credential_id, ticket.origin, authorized=True))
            script = fill_script(ticket.nonce, ticket.origin, login.username, login.password)
        except (ValueError, OSError, sqlite3.Error):
            callback(False)
            return

        def receive(raw):
            success = False
            try:
                success = (self._live() is not None and self._epoch == ticket.epoch
                           and isinstance(raw, str) and json.loads(raw) == {'ok': True})
            except (ValueError, TypeError, RuntimeError):
                pass
            callback(success)

        try:
            current.runJavaScript(script, 1, receive)
        except RuntimeError:
            callback(False)
