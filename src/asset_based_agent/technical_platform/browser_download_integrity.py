"""Native disk verification evidence, NOT task success or a website write receipt.

Run outside the GUI thread. A future completion confirmation must bind this
manifest to the user's goal and recheck live authority before settling a task.
"""
import json
from hashlib import sha256
from pathlib import Path

from .browser_download_artifacts import (
    DownloadArtifacts,
    check_download_identity,
    fingerprint_download,
)
from .browser_task_spec import BrowserTaskScope, browser_execution_goal
from .permissions import PermissionService

# login is the native credential-fill tool, never form submission or evidence
# of authenticated identity. This receipt verifies files, not a login outcome.
DOWNLOAD_DELIVERY_ACTIONS = frozenset({'observe', 'navigate', 'scroll', 'wait', 'download', 'login'})


def verify_download_delivery(store, run_id, cancel):
    def active():
        if cancel.is_set():
            raise InterruptedError('Download verification cancelled')
        PermissionService(store).verify(run_id)
        run = store.run(run_id)
        if run['state'] != 'running':
            raise PermissionError('Download task is not active')
        return run

    run = active()
    snapshot = json.loads(run['snapshot'])
    scope = BrowserTaskScope.model_validate(snapshot['browser_scope'])
    if (snapshot.get('mode') != 'browser_task' or snapshot.get('task_id') != run_id
            or 'download' not in scope.actions
            or not set(scope.actions) <= DOWNLOAD_DELIVERY_ACTIONS):
        raise PermissionError('Task is not a download-only delivery')
    artifacts = DownloadArtifacts(store)
    records = artifacts.list(run_id)
    if not 1 <= len(records) <= 32:
        raise ValueError('No bounded download delivery exists')
    files = []
    for record in records:
        active()
        provenance = record['provenance']
        if provenance is None or provenance['origin'] not in scope.origins:
            raise PermissionError('Download has no authorized source provenance')
        actual = fingerprint_download(Path(record['path']), record['size'], cancel)
        if any(actual[key] != record[key] for key in actual):
            raise ValueError('Download content or file identity changed')
        files.append({key: record[key] for key in ('id', 'name', 'size', 'sha256', 'file_identity')}
                     | {'origin': provenance['origin']})
    final = active()
    if final['snapshot'] != run['snapshot'] or artifacts.list(run_id) != records:
        raise PermissionError('Download delivery changed during verification')
    for record in records:
        active()
        check_download_identity(record)
    return {'task_id': run_id,
            'goal_sha256': sha256(browser_execution_goal(snapshot).encode()).hexdigest(),
            'files': files}
