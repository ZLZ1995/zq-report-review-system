"""Disk-worker preparation only; creating a copy never authorizes web transfer.

Incomplete directories remain quarantined for explicit recovery/cleanup. No
recursive cleanup and no guessed deletion of files potentially replaced by users.
"""
import os
from threading import Event
from uuid import uuid4

from .browser_download_artifacts import _path, _stamp, fingerprint_download
from .browser_upload_source import resolve_upload_source
from .project_catalog import validate_business_directory


def prepare_upload(store, session_id: str, reference: dict, cancel: Event) -> dict:
    source = resolve_upload_source(store, session_id, reference, cancel)
    path = _path(source['path'])
    root = validate_business_directory(store.path.parent) / 'browser_uploads'
    if root.resolve() != root:
        raise PermissionError('Upload staging directory redirected')
    root.mkdir(exist_ok=True)
    stage = root / uuid4().hex
    stage.mkdir(exist_ok=False)
    validate_business_directory(stage)
    if stage.resolve() != stage:
        raise PermissionError('Upload staging directory redirected')
    partial = stage / 'payload.partial'
    with path.open('rb') as incoming, partial.open('xb') as outgoing:
        if _stamp(os.fstat(incoming.fileno())) != source['file_identity']:
            raise ValueError('Upload source replaced before copy')
        while True:
            if cancel.is_set():
                raise InterruptedError('Upload preparation cancelled')
            chunk = incoming.read(1024 * 1024)
            if not chunk:
                break
            outgoing.write(chunk)
        outgoing.flush()
        os.fsync(outgoing.fileno())
        if _stamp(os.fstat(incoming.fileno())) != source['file_identity']:
            raise ValueError('Upload source changed during copy')
    copy = fingerprint_download(partial, source['size'], cancel)
    if (copy['sha256'] != source['sha256']
            or _stamp(path.stat()) != source['file_identity']):
        raise ValueError('Upload copy does not match validated source')
    # Recheck provenance after disk work, including source task and ownership.
    current = resolve_upload_source(store, session_id, reference, cancel)
    if current != source:
        raise ValueError('Upload source authorization metadata changed')
    target = stage / path.name
    if target == partial:
        raise ValueError('Reserved upload file name')
    os.link(partial, target)  # Atomic no-overwrite publication on the same volume.
    partial.unlink()
    result = fingerprint_download(target, source['size'], cancel)
    if result['sha256'] != source['sha256']:
        raise ValueError('Upload copy changed before delivery')
    return result
