"""Local download integrity and immutable task receipts; never a model tool."""
import json
import os
import stat
from hashlib import sha256
from pathlib import Path
from threading import Event
from uuid import uuid4

from pydantic import Field

from ..agent_contracts import Record
from .browser_policy import credential_origin, download_origin
from .browser_upload_target import upload_target_key
from .event_store import ExecutionStore
from .permissions import PermissionService
from .project_catalog import validate_business_directory
from .store import now


class DownloadFingerprint(Record):
    path: str = Field(min_length=1, max_length=32768)
    name: str = Field(min_length=1, max_length=180)
    size: int = Field(ge=0, strict=True)
    sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    file_identity: str = Field(pattern=r'^[0-9a-f]{64}$')


class DownloadProvenance(Record):
    origin: str
    target_key: str = Field(pattern=r'^[0-9a-f]{64}$')
    resource_sha256: str = Field(pattern=r'^[0-9a-f]{64}$')


class StoredDownload(DownloadFingerprint):
    provenance: DownloadProvenance | None = None


def _stamp(info):
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise ValueError('Download is not an independent regular file')
    # On Windows, stat-by-path and fstat-by-handle can expose different ctime
    # views for the same open file.  ctime is metadata-change time rather than
    # file identity, so binding it here rejects legitimate downloads on a
    # clean runner.  Device/inode/size/mtime plus the streamed SHA-256 retain
    # replacement and content-change detection without that false mismatch.
    return sha256(json.dumps([info.st_dev, info.st_ino, info.st_size,
                             info.st_mtime_ns]).encode()).hexdigest()


def _path(value):
    path = Path(value)
    if not path.is_absolute() or path.is_symlink() or path.resolve() != path:
        raise ValueError('Download path is redirected')
    validate_business_directory(path.parent)
    return path


def fingerprint_download(path: Path, expected_size: int, cancel: Event) -> dict:
    """Call from a worker: bounded-memory hashing, cancellation at every chunk."""
    if cancel.is_set():
        raise InterruptedError('Download verification cancelled')
    path = _path(path)
    before = _stamp(path.stat())
    digest = sha256()
    with path.open('rb') as stream:
        opened = os.fstat(stream.fileno())
        if _stamp(opened) != before or opened.st_size != expected_size:
            raise ValueError('Download file changed or has unexpected size')
        while True:
            if cancel.is_set():
                raise InterruptedError('Download verification cancelled')
            chunk = stream.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
        if _stamp(os.fstat(stream.fileno())) != before:
            raise ValueError('Download changed while reading')
    if cancel.is_set():
        raise InterruptedError('Download verification cancelled')
    if _stamp(path.stat()) != before or path.resolve() != path:
        raise ValueError('Download replaced while reading')
    return DownloadFingerprint(path=str(path), name=path.name, size=expected_size,
                               sha256=digest.hexdigest(), file_identity=before).model_dump()


def check_download_identity(record):
    """Cheap native recheck after worker hashing or a user confirmation dialog."""
    path = _path(record['path'])
    if path.name != record['name'] or _stamp(path.stat()) != record['file_identity']:
        raise ValueError('Downloaded file changed after verification')


class DownloadArtifacts:
    def __init__(self, store):
        self.store = store

    def save(self, request, receipt, url, fingerprint, *, source_url=None):
        item = DownloadFingerprint.model_validate(fingerprint)
        path = _path(item.path)
        values = {'url':url, 'destination':str(path)}
        provenance = None
        if source_url is not None:
            if credential_origin(source_url) != request.origin:
                raise PermissionError('Download source does not match authorized origin')
            values['source_url'] = source_url
            try:
                target_key = upload_target_key(source_url)
            except ValueError:
                # Unsupported business pages remain ordinary downloads, not readback proof.
                target_key = None
            if target_key is not None:
                provenance = DownloadProvenance(origin=request.origin, target_key=target_key,
                                                resource_sha256=sha256(url.encode()).hexdigest())
        binding = json.dumps(values, sort_keys=True, ensure_ascii=False)
        if (request.action != 'download' or download_origin(url) != request.origin
                or sha256(binding.encode()).hexdigest() != request.payload_sha256
                or path.name != item.name or _stamp(path.stat()) != item.file_identity):
            raise PermissionError('Download result does not match its authorization')
        payload = StoredDownload(**item.model_dump(), provenance=provenance).model_dump_json()
        digest = sha256(payload.encode()).hexdigest()
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            request, action_binding = PermissionService(self.store)._browser_binding(db, request)
            authorization = db.execute('SELECT binding_sha256,consumed FROM browser_action_authorizations '
                'WHERE id=? AND run=? AND step_id=?',
                (receipt, request.identity.task_id, request.step_id)).fetchone()
            if authorization is None or not authorization['consumed'] or authorization['binding_sha256'] != action_binding:
                raise PermissionError('Download has no consumed action receipt')
            previous = db.execute('SELECT id,sha256 FROM browser_download_artifacts WHERE receipt=?', (receipt,)).fetchone()
            if previous is not None:
                if previous['sha256'] != digest:
                    raise ValueError('Download receipt is immutable')
                return previous['id']
            if db.execute('SELECT COUNT(*) FROM browser_download_artifacts WHERE run=?',
                          (request.identity.task_id,)).fetchone()[0] >= 32:
                raise ValueError('Task download receipt limit exceeded')
            identity = uuid4().hex
            db.execute('INSERT INTO browser_download_artifacts VALUES(?,?,?,?,?,?,?)',
                (identity,request.identity.task_id,request.step_id,receipt,payload,digest,now()))
            return identity

    def list(self, run_id):
        with self.store.connect() as db:
            ExecutionStore(self.store)._run(db, run_id)
            rows = db.execute('SELECT id,payload,sha256 FROM browser_download_artifacts WHERE run=? ORDER BY created,id',
                              (run_id,)).fetchall()
            results = []
            for row in rows:
                if sha256(row['payload'].encode()).hexdigest() != row['sha256']:
                    raise ValueError('Download receipt integrity check failed')
                results.append({'id':row['id'], **StoredDownload.model_validate_json(row['payload']).model_dump()})
            return results

    def resolve(self, session_id, run_id, identity):
        if self.store.run(run_id)['session'] != session_id:
            raise PermissionError('Download belongs to another conversation')
        item = next((item for item in self.list(run_id) if item['id'] == identity), None)
        if item is None:
            raise PermissionError('Download receipt missing')
        actual = fingerprint_download(Path(item['path']), item['size'], Event())
        if any(actual[key] != item[key] for key in actual):
            raise ValueError('Downloaded file changed since verification')
        return Path(item['path'])
