from pathlib import Path
from types import SimpleNamespace

import pytest
from PySide6.QtWebEngineCore import QWebEngineDownloadRequest
from test_browser_download_controller import setup_controller


def task_controller(tmp_path):
    controller, request, destination = setup_controller(tmp_path)
    page = SimpleNamespace(_task_navigation_owner=SimpleNamespace(binding=SimpleNamespace(task_id='task-one')))
    request.source = page
    controller.session.owns_page = lambda candidate: candidate is page
    return controller, request, destination, page


def test_task_page_download_without_single_use_permission_is_rejected(tmp_path):
    controller, request, destination, _ = task_controller(tmp_path)
    choices = []
    controller.choose = lambda name: choices.append(name) or destination
    controller.request(request)
    assert not request.accepted and not choices and not destination.exists()
    controller.close()


def test_task_download_timer_cancels_without_network_progress(tmp_path):
    import os
    import subprocess
    import sys
    code = r'''
import sys
from pathlib import Path
from PySide6.QtCore import QCoreApplication
from PySide6.QtTest import QTest
from test_browser_task_downloads import task_controller
from asset_based_agent.technical_platform.browser_download_controller import TaskDownloadPermission
app=QCoreApplication([])
controller,request,destination,page=task_controller(Path(sys.argv[1]))
active=[True]; finished=[]
permission=TaskDownloadPermission('task-one',lambda:active[0],lambda *_:True,
    lambda status,record:finished.append(status))
controller.arm_task(page,permission); controller.request(request)
assert request.accepted and controller.timer.isActive()
active[0]=False
QTest.qWait(300)
assert finished==['cancelled'] and not destination.exists()
assert not controller.timer.isActive()
controller.close()
'''
    env = dict(os.environ, QT_QPA_PLATFORM='offscreen')
    env['PYTHONPATH'] = os.pathsep.join(['src', 'tests/technical_platform', env.get('PYTHONPATH', '')])
    result = subprocess.run([sys.executable, '-X', 'utf8', '-c', code, str(tmp_path)],
                            env=env, capture_output=True, text=True, encoding='utf-8', timeout=15, check=False)
    assert result.returncode == 0, result.stdout + result.stderr


def test_download_permission_cannot_claim_another_task(tmp_path):
    from asset_based_agent.technical_platform.browser_download_controller import (
        TaskDownloadPermission,
    )
    controller, _, _, page = task_controller(tmp_path)
    with pytest.raises(PermissionError):
        controller.arm_task(page, TaskDownloadPermission('other', lambda: True, lambda *_: True, lambda *_: None))
    controller.close()


def test_manual_picker_cannot_accept_after_page_becomes_task_owned(tmp_path):
    controller, request, destination, page = task_controller(tmp_path)
    owner, page._task_navigation_owner = page._task_navigation_owner, None
    def choose(_):
        page._task_navigation_owner = owner
        return destination
    controller.choose = choose
    controller.request(request)
    assert not request.accepted and not destination.exists()
    controller.close()


@pytest.mark.parametrize('case', ['complete', 'decline', 'revoked_before', 'revoked_picker',
                                 'revoked_running', 'revoked_complete', 'new_owner', 'foreign_url'])
def test_task_download_permission_survives_only_same_live_task(tmp_path, case):
    from asset_based_agent.technical_platform.browser_download_controller import (
        TaskDownloadPermission,
    )
    controller, request, destination, page = task_controller(tmp_path)
    active = [True]
    finished = []
    admitted = []
    def admit(url, path):
        admitted.append((url, path))
        return url == 'https://example.com/file' and case != 'foreign_url'
    permit = TaskDownloadPermission('task-one', lambda: active[0], admit,
                                    lambda status, record: finished.append((status, record)))
    controller.arm_task(page, permit)
    if case == 'revoked_before': active[0] = False
    def choose(_name):
        if case == 'revoked_picker': active[0] = False
        if case == 'new_owner': page._task_navigation_owner = object()
        return None if case == 'decline' else destination
    controller.choose = choose
    controller.request(request)
    if case in {'complete', 'revoked_running', 'revoked_complete'}:
        assert request.accepted
        assert controller.records[1].task_id == 'task-one'
        (Path(request.directory) / request.filename).write_bytes(b'data')
        if case != 'complete': active[0] = False
        if case == 'revoked_running': controller.check_tasks()
        else:
            request.status = QWebEngineDownloadRequest.DownloadState.DownloadCompleted
            request.stateChanged.emit(request.status)
        assert destination.exists() is (case == 'complete')
        assert finished[0][0] == ('completed' if case == 'complete' else 'cancelled')
    else:
        assert not request.accepted and not destination.exists()
        assert finished[0][0] == 'rejected'
    assert len(finished) == 1
    # A second request cannot reuse the permission, even on the same page.
    from test_browser_download_controller import Request
    second = Request(page)
    controller.request(second)
    assert not second.accepted and len(finished) == 1
    controller.close()
