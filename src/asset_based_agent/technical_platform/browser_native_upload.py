"""Native upload lifecycle. Only confirmed deliverable references enter this API."""
from threading import Event

from PySide6.QtCore import QObject, QTimer, Slot

from ..browser_contracts import UploadArtifact
from .browser_upload_authorization import UploadAuthorization
from .browser_upload_source import UploadSource
from .browser_upload_target import upload_target_key
from .browser_upload_transfer import UploadTransfer
from .browser_upload_worker import UploadPreparationWorker


class NativeTaskUpload(QObject):
    def __init__(self, native, observer, parent=None, *, artifacts=(), confirm_upload=None):
        super().__init__(parent)
        self.native, self.observer = native, observer
        self.closed = False
        self.worker = self.transfer = self.authorization = None
        self.callback = self.terminal = None
        self.cancel = Event()
        self.observation = None
        self.source = ''
        self.expected = None
        self.confirm_upload = confirm_upload
        self.artifacts: dict[str, tuple[UploadArtifact, UploadSource]] = {}
        self.attempted: set[str] = set()
        if len(artifacts) > 32:
            raise ValueError('Too many upload candidates')
        for item in artifacts:
            artifact = UploadArtifact.model_validate(item['artifact'])
            source = UploadSource.model_validate(item['source'])
            if artifact.id in self.artifacts or artifact.sha256 != source.sha256:
                raise ValueError('Upload candidate identity mismatch')
            self.artifacts[artifact.id] = (artifact, source)
        self.timer = QTimer(self)
        self.timer.setInterval(100)
        self.timer.timeout.connect(self._tick)

    def isRunning(self):
        return self.callback is not None or self.worker is not None

    def candidates(self):
        return [artifact.model_dump() for artifact, _ in self.artifacts.values()
                if artifact.sha256 not in self.attempted]

    def request(self, observation, proposal, callback):
        def valid():
            return (not self.closed and not self.isRunning() and not self.native.host.cancel.is_set()
                    and self.native.allowed('upload', observation.origin)
                    and self.observer.matches(self.native.lease, observation))
        try:
            if not valid() or self.confirm_upload is None or proposal.action != 'upload':
                raise PermissionError('Upload is unavailable')
            artifact, source = self.artifacts[proposal.artifact_id]
            if artifact.sha256 in self.attempted:
                raise PermissionError('Upload already attempted; reconcile website state')
            if self.confirm_upload(observation, proposal, artifact.model_dump(), valid) is not True or not valid():
                raise PermissionError('Upload was not confirmed')
        except Exception:  # noqa: BLE001
            callback('rejected')
            return
        self.begin(observation, proposal.target, source.model_dump(), proposal.object_label,
                   confirmed=True, callback=callback, expected=artifact)

    def active(self):
        try:
            return (not self.closed and self.callback is not None and self.terminal is None
                and self.observation is not None
                and not self.cancel.is_set() and not self.native.host.cancel.is_set()
                and self.native.allowed('upload', self.observation.origin)
                and not self.native.page.isLoading()
                and self.native.page.url().toString() == self.source
                and self.observer._epoch == self.observation.page_version
                and self.observer._nonce == self.observation.nonce)
        except Exception:  # noqa: BLE001 - native scope errors fail closed
            return False

    def begin(self, observation, target, reference, object_label, *, confirmed, callback, expected=None):
        if self.closed or self.isRunning() or confirmed is not True:
            callback('rejected')
            return
        self.callback = callback
        self.terminal = None
        self.cancel = Event()
        self.observation = observation
        self.expected = expected
        try:
            self.source = self.native.page.url().toString()
            target_key = upload_target_key(self.source)
            if not self.active() or not self.observer.matches(self.native.lease, observation):
                raise PermissionError('Upload observation changed')
            self.authorization = UploadAuthorization(self.native.host.store)
            fields = {'identity': self.native.identity.model_dump(),
                'step_id': self.native.host.plan.steps[0].step_id,
                'revision': self.native.host.plan.revision, 'claim_token': self.native.host.claim_token,
                'environment': self.native.scope.environment, 'tab_id': self.native.lease.tab_id,
                'page_version': observation.page_version, 'origin': observation.origin,
                'field_id': target, 'object_label': object_label, 'target_key': target_key}
            self.worker = UploadPreparationWorker(self.authorization, fields, reference,
                                                   self.cancel, confirmed=True, parent=self)
            self.worker.finished.connect(self._prepared)
            self.timer.start()
            self.worker.start()
        except Exception:  # noqa: BLE001
            # A thread that never started cannot emit finished. Running workers
            # must still finish before their authorization/QObject is released.
            if self.worker is not None and not self.worker.isRunning():
                self.worker.finished.disconnect(self._prepared)
                self.worker.deleteLater()
                self.worker = None
            self._finish('rejected')

    def _tick(self):
        if self.callback is not None and self.terminal is None and not self.active():
            self._finish('cancelled')

    @Slot()
    def _prepared(self):
        worker, self.worker = self.worker, None
        if worker is None:
            return
        result, worker.result = worker.result, None
        worker.deleteLater()
        if self.terminal is not None:
            self._emit()
            return
        if not self.active():
            self._finish('cancelled')
            return
        try:
            observation, authorization = self.observation, self.authorization
            if result is None or observation is None or authorization is None:
                raise ValueError('Upload preparation failed')
            permit, payload = result
            if self.expected is not None and any(
                    getattr(permit.scope.artifact, key) != getattr(self.expected, key)
                    for key in ('name', 'size', 'sha256')):
                raise PermissionError('Prepared artifact differs from confirmed candidate')
            if not self.observer.reserve_upload(self.native.lease, observation, permit.scope.field_id):
                raise PermissionError('Upload observation no longer available')
            def commit():
                if permit.scope.artifact.sha256 in self.attempted:
                    raise PermissionError('Upload already attempted')
                self.attempted.add(permit.scope.artifact.sha256)
                authorization.consume(permit, permit.scope, active=self.active())
            self.transfer = UploadTransfer(self.native.page, permit, observation.nonce,
                payload, active=self.active,
                commit=commit, parent=self)
            self.transfer.finished.connect(self._finish)
            self.transfer.start()
        except Exception:  # noqa: BLE001
            self._finish('rejected')

    def _finish(self, status):
        if self.callback is None or self.terminal is not None:
            return
        self.terminal = status
        self.timer.stop()
        self.cancel.set()
        if self.transfer is not None:
            self.transfer.close()
        if self.worker is None:
            self._emit()
        # Keep QObject/worker alive until its actual finished signal.

    def _emit(self):
        callback, self.callback = self.callback, None
        if self.authorization is not None:
            self.authorization.close()
            self.authorization = None
        if self.transfer is not None:
            self.transfer.deleteLater()
            self.transfer = None
        if callback is not None:
            callback(self.terminal)

    def close(self):
        self.closed = True
        self._finish('cancelled')
