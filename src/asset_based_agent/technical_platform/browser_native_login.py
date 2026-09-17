"""Native task-to-vault bridge. Only fill status leaves this local boundary."""
import sqlite3

from .browser_policy import credential_origin
from .browser_task_permissions import BrowserTaskPermissions, LoginScope
from .browser_trusted_login import TrustedLogin


class NativeTaskLogin:
    def __init__(self, native, observer, vault, *, select_account):
        self.native, self.observer, self.vault = native, observer, vault
        self.select_account = select_account
        self.permissions = BrowserTaskPermissions()
        self.bridge = None
        self.ticket = None
        self.selected = None
        self.callback = None
        self.closed = False
        self.page_version = None

    def _active(self):
        try:
            return (not self.closed and self.bridge is not None and self.ticket is not None
                    and self.native.allowed('login', self.ticket.origin)
                    and credential_origin(self.native.page.url().toString()) == self.ticket.origin
                    and not self.native.page.isLoading()
                    and self.bridge.page_version == self.ticket.epoch
                    and self.observer._epoch == self.page_version)
        except (ValueError, OSError, RuntimeError, sqlite3.Error):
            return False

    def _scope(self):
        if not self._active() or self.selected is None or self.ticket is None:
            return None
        return LoginScope(identity=self.native.identity, environment=self.native.scope.environment,
            revision=self.native.host.plan.revision, step_id=self.native.host.plan.steps[0].step_id,
            tab_id=self.native.lease.tab_id, page_version=self.ticket.epoch,
            origin=self.ticket.origin, credential_id=self.selected)

    def fill(self, callback):
        if self.closed or self.callback is not None:
            callback('rejected')
            return
        self.callback = callback
        try:
            origin = credential_origin(self.native.page.url().toString())
            if not self.native.allowed('login', origin):
                raise PermissionError('Login outside native task scope')
            self.page_version = self.observer._epoch
            self.bridge = TrustedLogin(self.native.leases.session, self.native.page, self.vault,
                tab_id=self.native.lease.tab_id, task_permissions=self.permissions, task_scope=self._scope)
            self.bridge.probe(self._probed)
        except (ValueError, OSError, RuntimeError, sqlite3.Error):
            self._finish('rejected')

    def _probed(self, ticket):
        if self.callback is None or self.closed:
            return
        self.ticket = ticket
        try:
            if not self._active():
                raise PermissionError('Login page changed')
            accounts = self.vault.agent_accounts(ticket.origin)
            if not accounts:
                raise PermissionError('No website account has agent consent')
            selected = self.select_account(ticket.origin, accounts, self._active)
            if (not self._active() or selected not in {account.key for account in accounts}
                    or selected not in {account.key for account in self.vault.agent_accounts(ticket.origin)}):
                raise PermissionError('Account selection or consent changed')
            self.selected = selected
            scope = self._scope()
            if scope is None or self.bridge is None:
                raise PermissionError('Task is no longer active')
            request = self.native.request(origin=ticket.origin, action='login',
                                          page_version=self.page_version, payload=selected)
            receipt = self.native.service.authorize_browser_action(request, confirmed=True)
            self.native.service.consume_browser_action(receipt, request)
            permit = self.permissions.authorize_login(scope, confirmed=True)
            self.bridge.fill_for_task(ticket, permit,
                callback=lambda ok: self._finish('dispatched' if ok else 'unknown'))
        except (ValueError, OSError, RuntimeError, sqlite3.Error):
            self._finish('rejected')

    def _finish(self, status):
        callback, self.callback = self.callback, None
        bridge, self.bridge = self.bridge, None
        self.ticket, self.selected = None, None
        if bridge is not None:
            bridge.close()
        if callback is not None:
            callback(status)

    def close(self):
        self.closed = True
        self.permissions.close()
        self._finish('cancelled')
