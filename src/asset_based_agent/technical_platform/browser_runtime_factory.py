"""Trusted native assembly. Confirmation callbacks must never come from a model."""
import json
import sqlite3
from hashlib import sha256

from ..agent_contracts import BrowserIntent
from .browser_action_gate import BrowserActionGate
from .browser_action_request import BrowserActionRequest
from .browser_credential_vault import CredentialVault
from .browser_execution_loop import BrowserExecutionLoop
from .browser_native_download import NativeTaskDownload
from .browser_native_login import NativeTaskLogin
from .browser_native_upload import NativeTaskUpload
from .browser_navigation import BrowserNavigation
from .browser_observer import BrowserObserver
from .browser_policy import credential_origin
from .browser_task_spec import BrowserTaskScope, browser_execution_goal
from .permissions import PermissionService
from .task_spec import snapshot_identity


class NativeBrowserScope:
    def __init__(self, host, leases, page, *, confirmed):
        self.host, self.leases, self.page = host, leases, page
        self.service = PermissionService(host.store)
        self.service.verify(host.run_id)
        self.snapshot = json.loads(host.store.run(host.run_id)['snapshot'])
        self.scope = BrowserTaskScope.model_validate(self.snapshot['browser_scope'])
        self.identity = snapshot_identity(self.snapshot)
        if (self.scope.environment != leases.session.environment
                or self.identity.task_id != host.run_id or host.plan is None
                or host.plan.identity != self.identity or not host.claim_token):
            raise PermissionError('Native browser task mismatch')
        binding = host.binding
        if ((binding.owner, binding.project_id, binding.session_id, binding.task_id)
                != (self.identity.owner, self.identity.project_id,
                    self.identity.session_id, self.identity.task_id)):
            raise PermissionError('Native browser binding mismatch')
        self.lease = leases.acquire(page, binding, host, confirmed=confirmed)

    def active(self):
        try:
            if not self.leases.valid(self.lease):
                return False
            self.service.verify(self.host.run_id)
            with self.host.store.connect() as db:
                step = db.execute('SELECT state,claim_token FROM execution_steps WHERE run=? AND step_id=?',
                    (self.host.run_id, self.host.plan.steps[0].step_id)).fetchone()
            return (step is not None and step['state'] == 'running'
                    and step['claim_token'] == self.host.claim_token)
        except (ValueError, OSError, RuntimeError, sqlite3.Error):
            return False

    def allowed(self, action, url):
        try:
            return (self.active() and action in self.scope.actions
                    and credential_origin(url) in self.scope.origins)
        except ValueError:
            return False

    def request(self, *, origin, action, page_version=0, payload=''):
        if not self.allowed(action, origin):
            raise PermissionError('Inactive browser action scope')
        return BrowserActionRequest(identity=self.identity, step_id=self.host.plan.steps[0].step_id,
            revision=self.host.plan.revision, claim_token=self.host.claim_token,
            environment=self.scope.environment, tab_id=self.lease.tab_id, page_version=page_version,
            origin=origin, action=action, target='native', payload_sha256=sha256(payload.encode()).hexdigest())

    def resolve(self, lease):
        if lease is not self.lease or not self.active():
            raise PermissionError('Foreign browser lease')
        # Gate replaces placeholder action/origin/target with the actual observed
        # action and then independently checks the durable scope before issuing.
        return self.request(origin=self.scope.origins[0], action=self.scope.actions[0])


class ConfirmedNavigation:
    def __init__(self, native, observer, confirm):
        self.native, self.observer, self.confirm = native, observer, confirm
        self.navigation = BrowserNavigation(native.leases, native.page, native.lease,
                                            can_navigate=lambda _lease, url: self.allowed(url))

    def allowed(self, url):
        return self.native.allowed('navigate', url)

    def navigate(self, url, callback):
        try:
            if not self.allowed(url) or self.native.page.isLoading():
                raise PermissionError('Navigation is outside the task scope')
            epoch = self.observer._epoch
            current_url = self.native.page.url().toString()
            request = self.native.request(origin=credential_origin(url), action='navigate',
                                          page_version=epoch, payload=url)
            if self.confirm(request, url) is not True:
                raise PermissionError('Navigation was not confirmed')
            if (not self.allowed(url) or self.observer._epoch != epoch
                    or self.native.page.url().toString() != current_url):
                raise PermissionError('Page or authorization changed during confirmation')
            receipt = self.native.service.authorize_browser_action(request, confirmed=True)
            self.native.service.consume_browser_action(receipt, request)
        except (ValueError, OSError, RuntimeError, sqlite3.Error):
            callback('rejected')
            return
        self.navigation.navigate(url, callback)

    def cancel(self):
        self.navigation.cancel()


def create_browser_runtime(host, client, leases, page, *, confirmed,
                           confirm_action, confirm_navigation, select_account=None, downloads=None,
                           upload_artifacts=(), confirm_upload=None):
    native = NativeBrowserScope(host, leases, page, confirmed=confirmed)
    observer = None
    navigation = None
    login = None
    download = None
    upload = None
    try:
        gate = BrowserActionGate(native.service, leases, resolve=native.resolve, confirm=confirm_action)
        observer = BrowserObserver(leases, page,
            can_observe=lambda lease, origin: lease is native.lease and native.allowed('observe', origin),
            can_click=gate.click, can_edit=gate.edit, can_scroll=gate.scroll, can_download=gate.download,
            can_upload=lambda lease, origin: confirm_upload is not None
                and lease is native.lease and native.allowed('upload', origin))
        navigation = ConfirmedNavigation(native, observer, confirm_navigation)
        if select_account is not None:
            vault = CredentialVault(leases.session.preferences, leases.session.owner,
                                    environment=leases.session.environment)
            login = NativeTaskLogin(native, observer, vault, select_account=select_account)
        if downloads is not None:
            if downloads.session is not leases.session:
                raise PermissionError('Download controller belongs to another browser session')
            download = NativeTaskDownload(native, observer, downloads)
        if confirm_upload is not None:
            upload = NativeTaskUpload(native, observer, parent=host,
                artifacts=upload_artifacts, confirm_upload=confirm_upload)
        loop = BrowserExecutionLoop(client, observer, navigation, leases, native.lease,
            task_id=host.run_id, model_id=native.snapshot['model'],
            goal=browser_execution_goal(native.snapshot),
            scope=BrowserIntent(origins=native.scope.origins, actions=native.scope.actions),
            authorized=native.active, parent=host, login=login, downloads=download, uploads=upload)
    except Exception:  # Release native resources, then propagate to the host.
        if upload is not None:
            upload.close()
        if download is not None:
            download.close()
        if login is not None:
            login.close()
        if observer is not None:
            observer.close()
        if navigation is not None:
            navigation.cancel()
        leases.release(native.lease)
        raise

    def cleanup():
        if upload is not None:
            upload.close()
        if download is not None:
            download.close()
        if login is not None:
            login.close()
        navigation.cancel()
        observer.close()
        leases.release(native.lease)
        # Retain the navigation guard until explicit manual takeover. A late
        # redirect must not escape the cancelled task's scope.
    host.finished.connect(cleanup)
    return loop
