"""Task-bound direct-link download. URLs and local paths stay in native code."""
import json
import sqlite3

from .browser_download_artifacts import DownloadArtifacts
from .browser_download_controller import TaskDownloadPermission
from .browser_policy import credential_origin, download_origin, navigation_url


class NativeTaskDownload:
    supports_generated = True

    def __init__(self, native, observer, controller):
        self.native, self.observer, self.controller = native, observer, controller
        self.closed = False
        self.callback = None
        self.permission = None
        self.page_version = None
        self.source = ''
        self.url = ''
        self.receipt = None
        self.action_request = None
        self.delivered = None
        self.generated = False

    def active(self):
        try:
            return (not self.closed and self.callback is not None
                    and self.native.allowed('download', self.source)
                    and self.native.page.url().toString() == self.source
                    and self.observer._epoch == self.page_version)
        except (ValueError, OSError, RuntimeError, sqlite3.Error):
            return False

    def begin(self, observation, target, callback):
        if self.closed or self.callback is not None:
            callback('rejected', None)
            return
        self.callback = callback
        self.receipt, self.action_request, self.delivered = None, None, None
        self.url = ''
        self.generated = False
        self.page_version = observation.page_version
        self.source = self.native.page.url().toString()
        if not self.active() or not self.observer.matches(self.native.lease, observation):
            self._finish('rejected')
            return
        control = next((c for c in getattr(observation, 'controls', ()) if c.id == target), None)
        if control is not None and control.kind == 'button':
            try:
                self.generated = True
                self.observer.download_button(self.native.lease, observation, target,
                                              before_dispatch=self._arm_generated,
                                              callback=self._button_dispatched)
            except (ValueError, OSError, RuntimeError, sqlite3.Error):
                self._finish('unknown')
        else:
            self.observer.resolve_download(self.native.lease, observation, target, callback=self._resolved)

    def _arm_generated(self):
        if not self.active():
            return False
        self.permission = TaskDownloadPermission(self.native.identity.task_id, self.active,
            self._admit, self._delivered, allow_blob=True)
        self.controller.arm_task(self.native.page, self.permission)
        return self.active()

    def _button_dispatched(self, status):
        # A completed download can race the JavaScript acknowledgement.
        if self.callback is not None and status != 'dispatched':
            self._finish('rejected' if status == 'rejected' else 'unknown')

    def _resolved(self, url):
        try:
            if not self.active() or not url or credential_origin(url) != credential_origin(self.source):
                raise PermissionError('Download target changed')
            self.url = url
            self.permission = TaskDownloadPermission(self.native.identity.task_id, self.active,
                                                      self._admit, self._delivered)
            self.controller.arm_task(self.native.page, self.permission)
            self.native.page.download(navigation_url(url))
        except (ValueError, OSError, RuntimeError, sqlite3.Error):
            self._finish('rejected')

    def _admit(self, url, destination):
        if (not self.active() or (not self.generated and url != self.url)
                or download_origin(url) != credential_origin(self.source)):
            return False
        self.url = url
        request = self.native.request(origin=download_origin(url), action='download',
            page_version=self.page_version, payload=json.dumps({'url':url,'destination':str(destination),
                                                               'source_url':self.source},
                                                               sort_keys=True, ensure_ascii=False))
        # Destination was chosen in the local save dialog, not supplied by a model.
        receipt = self.native.service.authorize_browser_action(request, confirmed=True)
        self.native.service.consume_browser_action(receipt, request)
        self.receipt, self.action_request = receipt, request
        return self.active()

    def _delivered(self, status, record):
        if status != 'completed' or record is None:
            self._finish(status)
            return
        try:
            path = record.target.destination
            if (not self.active() or record.task_id != self.native.identity.task_id
                    or path.is_symlink() or path.resolve() != path or not path.is_file()
                    or path.stat().st_size != record.received):
                raise ValueError('Downloaded file does not match delivery record')
            self.delivered = {'task_id':record.task_id, 'path':str(path),
                'name':path.name, 'size':record.received, 'origin':download_origin(self.url)}
            self._finish('downloaded', self.delivered)
        except (ValueError, OSError, RuntimeError):
            self._finish('unknown')

    def _finish(self, status, record=None):
        callback, self.callback = self.callback, None
        permission, self.permission = self.permission, None
        if permission is not None:
            self.controller.disarm_task(self.native.page, permission)
        if callback is not None:
            callback(status, record)

    def commit_verified(self, fingerprint):
        if (self.closed or self.delivered is None or self.action_request is None or self.receipt is None
                or not self.native.allowed('download', self.source)
                or self.native.page.url().toString() != self.source or self.observer._epoch != self.page_version
                or any(fingerprint.get(key) != self.delivered[key] for key in ('path', 'name', 'size'))):
            raise PermissionError('Download context changed during verification')
        identity = DownloadArtifacts(self.native.host.store).save(
            self.action_request, self.receipt, self.url, fingerprint, source_url=self.source)
        return {**self.delivered, **fingerprint, 'id':identity}

    def close(self):
        self.closed = True
        self._finish('cancelled')
