"""Native-only upload source resolution. This is not website upload permission.

Call in a disk worker before a separate website/object-specific confirmation.
Only registered, versioned deliverables are eligible; model paths are forbidden.
"""
import json
from pathlib import Path
from threading import Event
from typing import Literal

from pydantic import Field

from ..agent_contracts import Record
from .browser_download_artifacts import fingerprint_download
from .generation_paths import generation_work_directory


class UploadSource(Record):
    run_id: str = Field(pattern=r'^[0-9a-f]{32}$')
    kind: Literal['generation', 'review']
    index: int = Field(ge=0, strict=True)
    sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    step_index: int | None = Field(default=None, ge=0, strict=True)


def resolve_upload_source(store, session_id: str, reference: dict, cancel: Event) -> dict:
    if cancel.is_set():
        raise InterruptedError('Upload preparation cancelled')
    ref = UploadSource.model_validate(reference)
    run = store.run(ref.run_id)
    if run['session'] != session_id or run['state'] != 'succeeded':
        raise PermissionError('Upload source is not a completed task in this conversation')
    result = json.loads(run['result'] or '{}')
    step_id = None
    if ref.step_index is not None:
        from .plan_results import completed_step_results
        records = completed_step_results(store, session_id, ref.run_id)
        if ref.step_index >= len(records):
            raise ValueError('Unknown artifact producer step')
        record = records[ref.step_index]
        step_id, result = record['step_id'], record['result']
        if ref.kind == 'review':
            from .review_delivery import step_review_store
            view = step_review_store(store, session_id, ref.run_id, ref.step_index)
            result = json.loads(view.run(ref.run_id)['result'])
    if result.get('kind') != ref.kind:
        raise PermissionError('Source is not the selected deliverable type')
    if ref.kind == 'generation':
        items = result.get('artifacts', [])
        if result.get('ok') is not True or ref.index >= len(items):
            raise ValueError('No validated generated artifact')
        item = items[ref.index]
        path = Path(item['path'])
        root = generation_work_directory(store.path.parent, ref.run_id, step_id) / 'output'
        if not path.is_relative_to(root) or path.name != item['name']:
            raise PermissionError('Artifact is outside its producer directory')
        version = item['sha256']
        size = path.stat().st_size
    else:
        paths = ([result['exported_report']] if result.get('exported_report') else [])
        paths += [p for batch in result.get('annotations', []) for p in batch['files']]
        if ref.index >= len(paths):
            raise ValueError('No registered review deliverable')
        path = Path(paths[ref.index])
        recorded = result.get('delivery_versions', {}).get(str(path))
        if not isinstance(recorded, dict):
            raise ValueError('Review deliverable has no recorded version')
        version, size = recorded['sha256'], recorded['size']
    if version != ref.sha256:
        raise ValueError('Selected artifact version changed')
    if (type(size) is not int or not 0 <= size <= 64 * 1024 * 1024
            or path.stat().st_size != size):
        raise ValueError('Upload size is unsupported or changed')
    sources = store.files(store.session(session_id)['project'])
    sources += json.loads(run['snapshot']).get('files', [])
    if any(path.resolve() == Path(item['path']).resolve() or item.get('sha256') == ref.sha256
           for item in sources):
        raise PermissionError('Original input files cannot be uploaded')
    actual = fingerprint_download(path, size, cancel)
    if actual['sha256'] != ref.sha256:
        raise ValueError('Artifact content changed after validation')
    # Return to native preparation only, never include this record in model DTOs.
    return actual
