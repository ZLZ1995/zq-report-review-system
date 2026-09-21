"""Bridge prepared artifacts to durable action receipts, never a model tool.

authorize performs disk verification and must run off the GUI thread. consume
must be followed by native page/field revalidation before returning a file.
"""
import json
import re
import sqlite3
import time
from hashlib import sha256

from .browser_action_request import BrowserActionRequest
from .browser_download_artifacts import _path, _stamp, fingerprint_download
from .browser_upload_permissions import UploadPermissions, UploadScope
from .browser_upload_source import UploadSource, resolve_upload_source
from .permissions import PermissionService
from .store import now


class UploadAuthorization:
    def __init__(self, store):
        self.store = store
        self.permissions = UploadPermissions()
        self._requests = {}

    def _staged(self, scope):
        path = _path(scope.artifact.path)
        root = self.store.path.parent / 'browser_uploads'
        if (path.parent.parent != root or not re.fullmatch('[0-9a-f]{32}', path.parent.name)
                or path.name != scope.artifact.name
                or _stamp(path.stat()) != scope.artifact.file_identity):
            raise PermissionError('Upload copy is outside its verified staging directory')
        return path

    def _operation(self, scope):
        # Independent of task, page, control and staging IDs so a restart or
        # newly planned task cannot silently repeat an uncertain external write.
        identity = scope.identity
        payload = [identity.owner, identity.project_id, identity.session_id,
                   scope.environment, scope.origin, scope.target_key or scope.object_label,
                   scope.artifact.sha256]
        return sha256(json.dumps(payload, ensure_ascii=False).encode()).hexdigest()

    def authorize(self, scope, reference, *, confirmed, cancel):
        if confirmed is not True:
            raise PermissionError('Upload requires explicit confirmation')
        scope = UploadScope.model_validate(scope.model_dump())
        reference = UploadSource.model_validate(reference).model_dump()
        if scope.identity.owner != self.store.owner:
            raise PermissionError('Upload owner changed')
        with self.store.connect() as db:
            self._check_prior(db, scope)
        path = self._staged(scope)
        original = resolve_upload_source(self.store, scope.identity.session_id, reference, cancel)
        copy = fingerprint_download(path, scope.artifact.size, cancel)
        if (copy != scope.artifact.model_dump() or copy['sha256'] != original['sha256']
                or copy['size'] != original['size']):
            raise ValueError('Prepared upload does not match the approved deliverable')
        payload = json.dumps({'object': scope.object_label, 'target_key': scope.target_key, 'source': reference,
                              'artifact': copy}, sort_keys=True, ensure_ascii=False)
        request = BrowserActionRequest(identity=scope.identity, step_id=scope.step_id,
            revision=scope.revision, claim_token=scope.claim_token, environment=scope.environment,
            tab_id=scope.tab_id, page_version=scope.page_version, origin=scope.origin,
            action='upload', target=scope.field_id, payload_sha256=sha256(payload.encode()).hexdigest())
        self._requests = {k: entry for k, entry in self._requests.items() if entry[0].expires > time.monotonic()}
        if len(self._requests) >= 128:
            raise PermissionError('Too many pending upload authorizations')
        if cancel.is_set():
            raise InterruptedError('Upload cancelled')
        receipt = PermissionService(self.store).authorize_browser_action(request, confirmed=True)
        if cancel.is_set():
            raise InterruptedError('Upload cancelled')
        permit = self.permissions.authorize(scope.model_copy(update={'receipt_id': receipt}), confirmed=True)
        self._requests[permit.key] = (permit, request)
        return permit

    def _check_prior(self, db, scope):
        if db.execute('SELECT 1 FROM browser_upload_attempts WHERE operation_sha256=?',
                      (self._operation(scope),)).fetchone():
            raise PermissionError('Upload already attempted; reconcile website state')
        if not scope.target_key:
            return
        rows = db.execute(
            'SELECT a.metadata FROM browser_upload_attempts a JOIN runs r ON r.id=a.run '
            'JOIN sessions s ON s.id=r.session JOIN projects p ON p.id=s.project '
            'WHERE s.id=? AND p.owner=? AND a.state=?',
            (scope.identity.session_id, self.store.owner, 'unknown'))
        for row in rows:
            metadata = json.loads(row[0]) if row[0] else None
            if metadata is None or not isinstance(metadata, dict):
                raise PermissionError('Legacy upload requires reconciliation; reconcile website state')
            if (not metadata.get('target_key') and metadata.get('origin') == scope.origin
                    and metadata.get('sha256') == scope.artifact.sha256):
                raise PermissionError('Legacy upload already attempted; reconcile website state')

    def consume(self, permit, current, *, active):
        entry = self._requests.pop(permit.key, None)
        if not self.permissions.consume(permit, current, active=active) or entry is None or entry[0] is not permit:
            raise PermissionError('Upload permit unavailable or context changed')
        self._staged(current)
        PermissionService(self.store).consume_browser_action(current.receipt_id, entry[1])
        # Commit the conservative unknown marker BEFORE the page receives any
        # bytes. A crash here can cause a false unknown, never an automatic replay.
        try:
            with self.store.connect() as db:
                db.execute('BEGIN IMMEDIATE')
                self._check_prior(db, current)
                metadata = {'origin': current.origin, 'object_label': current.object_label,
                            'name': current.artifact.name, 'size': current.artifact.size,
                            'sha256': current.artifact.sha256, 'target_key': current.target_key}
                db.execute('INSERT INTO browser_upload_attempts '
                           '(operation_sha256,receipt,run,state,created,metadata) VALUES(?,?,?,?,?,?)',
                           (self._operation(current), current.receipt_id,
                            current.identity.task_id, 'unknown', now(),
                            json.dumps(metadata, ensure_ascii=False)))
        except sqlite3.IntegrityError as exc:
            raise PermissionError('Upload already attempted; reconcile website state') from exc

    def close(self):
        self.permissions.close()
        self._requests.clear()
