"""Native confirmation of worker-verified downloads; never a website write receipt."""
import json
import sqlite3
from copy import deepcopy
from hashlib import sha256
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .browser_download_artifacts import DownloadArtifacts, check_download_identity
from .browser_download_integrity import DOWNLOAD_DELIVERY_ACTIONS
from .browser_task_spec import BrowserTaskScope, browser_execution_goal
from .permissions import PermissionService
from .store import now


class DeliveredFile(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True, frozen=True)
    id: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=180)
    size: int = Field(ge=0)
    sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    file_identity: str = Field(pattern=r'^[0-9a-f]{64}$')
    origin: str = Field(min_length=1, max_length=2048)


class DownloadReceipt(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True, frozen=True)
    method: Literal['user_confirmed_download']
    task_id: str = Field(min_length=1, max_length=128)
    goal_sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    summary_sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    evidence_sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    files: list[DeliveredFile] = Field(min_length=1, max_length=32)
    confirmed_at: str = Field(min_length=1, max_length=64)


def validate_download_receipt(value, snapshot, detail):
    receipt = DownloadReceipt.model_validate(value)
    scope = BrowserTaskScope.model_validate(snapshot['browser_scope'])
    if (snapshot.get('mode') != 'browser_task' or 'download' not in scope.actions
            or not set(scope.actions) <= DOWNLOAD_DELIVERY_ACTIONS
            or receipt.task_id != snapshot['task_id']
            or receipt.goal_sha256 != sha256(browser_execution_goal(snapshot).encode()).hexdigest()
            or any(item.origin not in scope.origins for item in receipt.files)
            or len({item.id for item in receipt.files}) != len(receipt.files)):
        raise ValueError('Download receipt does not match task')
    for field in ('summary', 'evidence'):
        text = detail.get(field)
        if (not isinstance(text, str) or not text.strip() or len(text) > 2000
                or getattr(receipt, field + '_sha256') != sha256(text.encode()).hexdigest()):
            raise ValueError('Download receipt does not match result')
    return receipt.model_dump()


def confirm_download_delivery(store, run_id, cancel, manifest, detail, *, confirm, is_current):
    """Only accepts a native worker manifest. Recheck after the modal user decision.

    This helper does not hash on the GUI thread and is not a model/API endpoint.
    The caller must retain the completed worker's manifest and live tab lease.
    """
    try:
        snapshot_text = store.run(run_id)['snapshot']
        snapshot = json.loads(snapshot_text)
        frozen_manifest = deepcopy(manifest)
        receipt = validate_download_receipt({
            **frozen_manifest, 'method': 'user_confirmed_download',
            'summary_sha256': sha256(detail['summary'].encode()).hexdigest(),
            'evidence_sha256': sha256(detail['evidence'].encode()).hexdigest(),
            'confirmed_at': now(),
        }, snapshot, detail)

        def active():
            try:
                PermissionService(store).verify(run_id)
                run = store.run(run_id)
                if (cancel.is_set() or is_current() is not True or run['state'] != 'running'
                        or run['snapshot'] != snapshot_text or manifest != frozen_manifest
                        or receipt['task_id'] != run_id):
                    return False
                records = DownloadArtifacts(store).list(run_id)
                files = []
                for record in records:
                    check_download_identity(record)
                    files.append({key: record[key] for key in
                                  ('id', 'name', 'size', 'sha256', 'file_identity')}
                                 | {'origin': record['provenance']['origin']})
                return files == receipt['files']
            except (ValueError, OSError, RuntimeError, KeyError, TypeError, sqlite3.Error):
                return False

        shown = deepcopy(detail) | {'files': deepcopy(receipt['files'])}
        if not active() or confirm(snapshot, shown, active) is not True or not active():
            return None
        return receipt
    except (ValueError, OSError, RuntimeError, KeyError, TypeError, sqlite3.Error):
        return None
