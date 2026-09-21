"""Trusted local submit capture in ApplicationWorld, never a generic host bridge.

User-initiated POST or method/action-less SPA button logins are captured. Success is NOT
inferred from a redirect. The local UI must explicitly confirm successful login
and persistence. Scripts do not cancel/replay a website submission.
"""
import json
import sqlite3
import weakref
from uuid import uuid4

from PySide6.QtCore import QFile, QIODevice, QObject, QTimer, Signal, Slot
from PySide6.QtWebChannel import QWebChannel

from .browser_credential_vault import CredentialVault
from .browser_login_scripts import _CHECKS
from .browser_pending_login import PendingLogin
from .browser_policy import credential_origin


def capture_script(nonce: str) -> str:
    resource = QFile(':/qtwebchannel/qwebchannel.js')
    if not resource.open(QIODevice.OpenModeFlag.ReadOnly):
        raise ValueError('Trusted login capture unavailable')
    library = bytes(resource.readAll().data()).decode('utf-8')
    resource.close()
    return library + '\n(function(nonce){try{' + _CHECKS + r'''
if (window !== window.top || location.protocol !== 'https:') return;
globalThis.__zqCaptureAbort?.abort();
const controller = new AbortController();
globalThis.__zqCaptureAbort = controller;
new QWebChannel(qt.webChannelTransport, channel => {
  const bridge = channel.objects.loginCapture;
  const capture = (event, f) => {
    try {
      if (!event.isTrusted || !navigator.userActivation.isActive) return;
      if (!(f instanceof HTMLFormElement)) return;
      const inputs = Array.from(f.elements).filter(e => e instanceof HTMLInputElement && visible(e));
      const passwords = inputs.filter(e => e.type === 'password');
      const users = inputs.filter(e => ['text','email','tel'].includes(e.type));
      const named = users.filter(e => e.autocomplete === 'username');
      const candidates = named.length ? named : users;
      if (passwords.length !== 1 || candidates.length !== 1) return;
      const u = candidates[0], p = passwords[0];
      if (!valid(f,u,p) || !u.value || !p.value || u.value.length>2048 || p.value.length>8192) return;
      bridge.submitted(nonce, location.origin, u.value, p.value);
    } catch (_) { /* No credential-bearing errors or logs. */ }
  };
  document.addEventListener('submit', event => {
    if (event.target instanceof HTMLFormElement && modeOf(event.target)==='post') capture(event,event.target);
  }, {capture:true, signal:controller.signal});
  document.addEventListener('click', event => {
    const b = event.target instanceof Element ? event.target.closest('button,input[type=button]') : null;
    if (b && b.type==='button' && b.form && modeOf(b.form)==='script') capture(event,b.form);
  }, {capture:true, signal:controller.signal});
  bridge.ready(nonce);
});
}catch(_){} })(''' + json.dumps(nonce) + ')'


class LoginCapture(QObject):
    changed = Signal()  # Deliberately no credential payload on a Qt signal.

    def __init__(self, session, page, vault: CredentialVault):
        if (not session.owns_page(page) or session.owner != vault.owner
                or session.environment != vault.environment or session.preferences is not vault.preferences):
            raise ValueError('Login capture ownership mismatch')
        super().__init__(page)
        self.session, self.vault = session, vault
        self._page = weakref.ref(page)
        self._closed = False
        self._nonce = ''
        self._origin = ''
        self.armed = False
        self.pending: PendingLogin | None = None
        self.flow_id = ''
        self.origin = ''
        self.username = ''  # Local UI only, never sent to Agent observations.
        self.expiry = QTimer(self)
        self.expiry.setSingleShot(True)
        self.expiry.setInterval(120000)
        self.expiry.timeout.connect(self.discard)
        self.channel = QWebChannel(self)
        self.channel.registerObject('loginCapture', self)
        page.setWebChannel(self.channel, 1)
        page.loadStarted.connect(self._started)
        page.loadFinished.connect(self._loaded)
        page.urlChanged.connect(self._url_changed)
        page.renderProcessTerminated.connect(self.discard)

    def _live(self):
        page = self._page()
        return page if not self._closed and page is not None and self.session.owns_page(page) else None

    def _started(self):
        self.armed = False
        self._nonce = ''
        self.changed.emit()

    def _url_changed(self, *_args):
        page = self._live()
        try:
            if page is None or credential_origin(page.url().toString()) != self.origin:
                self.discard()
        except ValueError:
            self.discard()

    def _loaded(self, ok):
        page = self._live()
        if page is None or not ok:
            self.discard()
            return
        try:
            self._origin = credential_origin(page.url().toString())
            self._nonce = uuid4().hex
            page.runJavaScript(capture_script(self._nonce), 1)
        except (ValueError, RuntimeError):
            self._started()

    def _matches(self, nonce: str) -> bool:
        page = self._live()
        try:
            return (page is not None and not page.isLoading() and bool(self._nonce)
                    and nonce == self._nonce and credential_origin(page.url().toString()) == self._origin)
        except (ValueError, RuntimeError):
            return False

    @Slot(str)
    def ready(self, nonce):
        self.armed = self._matches(nonce)
        self.changed.emit()

    @Slot(str, str, str, str)
    def submitted(self, nonce, origin, username, password):
        if not self.armed or not self._matches(nonce) or origin != self._origin:
            return
        self.discard()
        try:
            if self.vault.prompt_policy(origin) == 'never':
                return
            flow = uuid4().hex
            pending = PendingLogin(self.vault, origin, username, password, flow_id=flow)
        except (ValueError, OSError, sqlite3.Error):
            return
        self.pending, self.flow_id = pending, flow
        self.origin, self.username = origin, username
        self.expiry.start()
        self.changed.emit()

    def discard(self, *_args):
        if self.pending is not None:
            self.pending.discard()
        self.pending = None
        self.flow_id = self.origin = self.username = ''
        self.expiry.stop()
        self.changed.emit()

    def save(self, *, confirmed: bool, login_succeeded: bool, replace_id: str | None = None) -> str:
        page, pending, flow = self._live(), self.pending, self.flow_id
        self.pending = None
        self.discard()
        if pending is None:
            raise PermissionError('No pending login')
        if page is None or page.isLoading():
            pending.discard()
            raise PermissionError('Login page unavailable')
        return pending.save(page.url().toString(), flow_id=flow, confirmed=confirmed,
                            login_succeeded=login_succeeded, replace_id=replace_id)

    def close(self):
        page = self._live()
        self._closed = True
        self._started()
        self.discard()
        if page is not None:
            page.loadStarted.disconnect(self._started)
            page.loadFinished.disconnect(self._loaded)
            page.urlChanged.disconnect(self._url_changed)
            page.renderProcessTerminated.disconnect(self.discard)
            page.setWebChannel(None, 1)
