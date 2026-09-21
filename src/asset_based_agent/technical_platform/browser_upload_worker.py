"""Prepare immutable upload bytes off the GUI thread; never interact with a page."""
import os
from copy import deepcopy
from hashlib import sha256

from PySide6.QtCore import QThread

from .browser_download_artifacts import DownloadFingerprint, _path, _stamp
from .browser_upload_permissions import UploadScope
from .browser_upload_preparation import prepare_upload
from .browser_upload_source import UploadSource


class UploadPreparationWorker(QThread):
    def __init__(self, authorization, scope_fields, reference, cancel, *, confirmed=False, parent=None):
        super().__init__(parent)
        self.authorization = authorization
        self.scope_fields = deepcopy(scope_fields)
        self.reference = UploadSource.model_validate(reference).model_dump()
        self.cancel = cancel
        self.confirmed = confirmed is True
        self.result = None

    def run(self):
        try:
            if not self.confirmed or self.cancel.is_set():
                return
            prepared = prepare_upload(self.authorization.store,
                self.scope_fields['identity']['session_id'], self.reference, self.cancel)
            path = _path(prepared['path'])
            if not 0 <= prepared['size'] <= 64 * 1024 * 1024:
                raise ValueError('Upload exceeds supported size')
            payload = bytearray()
            digest = sha256()
            with path.open('rb') as incoming:
                if _stamp(os.fstat(incoming.fileno())) != prepared['file_identity']:
                    raise ValueError('Upload copy changed')
                while True:
                    if self.cancel.is_set():
                        raise InterruptedError('Upload cancelled')
                    chunk = incoming.read(65536)
                    if not chunk:
                        break
                    if len(payload) + len(chunk) > prepared['size']:
                        raise ValueError('Upload copy grew')
                    payload.extend(chunk)
                    digest.update(chunk)
                if _stamp(os.fstat(incoming.fileno())) != prepared['file_identity']:
                    raise ValueError('Upload copy changed')
            if (len(payload) != prepared['size'] or digest.hexdigest() != prepared['sha256']
                    or _stamp(path.stat()) != prepared['file_identity']):
                raise ValueError('Upload copy verification failed')
            scope = UploadScope(**self.scope_fields,
                artifact=DownloadFingerprint.model_validate(prepared), receipt_id='pending')
            permit = self.authorization.authorize(scope, self.reference, confirmed=True, cancel=self.cancel)
            if not self.cancel.is_set():
                self.result = (permit, bytes(payload))
        except Exception:  # noqa: BLE001 - do not leak paths or credential-bearing exceptions
            self.result = None
