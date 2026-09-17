"""Native bounded byte delivery. Callers supply live scope and durable commit gates.

No model-facing entry point. Dispatched does not prove a website business receipt.
"""
import base64
import json
import time

from PySide6.QtCore import QObject, QTimer, Signal

from .browser_upload_script import upload_script


class UploadTransfer(QObject):
    finished = Signal(str)

    def __init__(self, page, permit, nonce, payload, *, active, commit, parent=None):
        super().__init__(parent)
        if type(payload) is not bytes or len(payload) != permit.scope.artifact.size:
            raise ValueError('Immutable verified payload required')
        self.page, self.permit, self.nonce = page, permit, nonce
        self.payload, self.active, self.commit = payload, active, commit
        self.offset = 0
        self.started = self.done = False
        self.sequence = 0
        self.deadline = 0.0
        self.timer = QTimer(self)
        self.timer.setInterval(100)
        self.timer.timeout.connect(self._check)

    def _check(self):
        if self.done:
            return False
        try:
            if self.active() is not True:
                self._finish('cancelled')
                return False
            if time.monotonic() > self.deadline:
                self._finish('unknown')
                return False
            return True
        except Exception:  # noqa: BLE001 - native scope errors must not escape Qt callbacks
            self._finish('rejected')
            return False

    def start(self):
        if self.started:
            raise RuntimeError('Upload transfer cannot restart')
        self.started = True
        self.deadline = time.monotonic() + 60
        self.timer.start()
        scope = self.permit.scope
        self._send('begin', self._chunk, origin=scope.origin, nonce=self.nonce,
                   target=scope.field_id, name=scope.artifact.name,
                   size=scope.artifact.size, sha256=scope.artifact.sha256)

    def _send(self, operation, continuation, **kwargs):
        if not self._check():
            return
        self.sequence += 1
        sequence = self.sequence
        def receive(raw):
            if sequence != self.sequence or self.done:
                return
            self.sequence += 1  # Consume even malformed/duplicate callbacks.
            if not self._check():
                return
            try:
                if not isinstance(raw, str) or len(raw) > 100:
                    raise ValueError('Invalid upload response')
                data = json.loads(raw)
                if set(data) != {'status'}:
                    raise ValueError('Invalid upload response')
                continuation(data['status'])
            except Exception:  # noqa: BLE001
                self._finish('unknown')
        try:
            self.page.runJavaScript(upload_script(operation, self.permit.key, **kwargs), 1, receive)
        except Exception:  # noqa: BLE001
            self._finish('unknown')

    def _chunk(self, status):
        if status != 'ready':
            self._finish('rejected')
            return
        if self.offset == len(self.payload):
            self._send('finish', self._verified)
            return
        offset = self.offset
        data = base64.b64encode(self.payload[offset:offset + 65536]).decode('ascii')
        self.offset += min(65536, len(self.payload) - offset)
        QTimer.singleShot(0, self, lambda: self._send('chunk', self._chunk, data=data, offset=offset))

    def _verified(self, status):
        if status == 'verifying':
            QTimer.singleShot(20, self, lambda: self._send('status', self._verified))
        elif status == 'verified' and self._check():
            # Runs after asynchronous hashing, immediately before the only side effect.
            self.commit()
            self._send('commit', lambda value: self._finish(
                'dispatched' if value == 'dispatched' else 'unknown'))
        else:
            self._finish('rejected')

    def _finish(self, status):
        if self.done:
            return
        self.done = True
        self.sequence += 1
        self.timer.stop()
        self.payload = b''
        if status != 'dispatched':
            try:
                self.page.runJavaScript(upload_script('abort', self.permit.key), 1)
            except Exception:  # noqa: BLE001, S110 - destroyed page; never log payloads/paths
                pass
        self.finished.emit(status)

    def close(self):
        self._finish('cancelled')
