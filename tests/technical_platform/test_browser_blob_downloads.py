from pathlib import Path
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QUrl
from PySide6.QtWebEngineCore import QWebEngineDownloadRequest
from test_browser_download_controller import setup_controller


@pytest.mark.parametrize('case', ['complete', 'foreign', 'opaque', 'http', 'picker_change',
                                  'running_change', 'cancel', 'task_default', 'task_allowed'])
def test_blob_download_requires_same_https_page_and_explicit_destination(tmp_path, case):
    controller, request, destination = setup_controller(tmp_path)
    current = ['https://example.com/page']
    page = SimpleNamespace(url=lambda: QUrl(current[0]), isLoading=lambda: False)
    request.source = page
    controller.session.owns_page = lambda candidate: candidate is page
    value = 'blob:https://example.com/12345678-1234-1234-1234-123456789abc'
    if case == 'foreign': value = value.replace('example.com', 'other.test')
    if case == 'opaque': value = 'blob:null/12345678'
    if case == 'http':
        current[0] = 'http://example.com/page'
        value = value.replace('https:', 'http:')
    request.url = lambda: QUrl(value)
    choices = []
    def choose(_):
        choices.append(True)
        if case == 'picker_change': current[0] = 'https://example.com/other'
        return destination
    controller.choose = choose
    if case in {'task_default', 'task_allowed'}:
        from asset_based_agent.technical_platform.browser_download_controller import (
            TaskDownloadPermission,
        )
        page._task_navigation_owner = SimpleNamespace(binding=SimpleNamespace(task_id='test'))
        controller.arm_task(page, TaskDownloadPermission('test', lambda: True, lambda *_: True,
                                                       lambda *_: None, allow_blob=case == 'task_allowed'))
    controller.request(request)
    if case in {'complete', 'running_change', 'cancel', 'task_allowed'}:
        assert request.accepted and choices
        (Path(request.directory) / request.filename).write_bytes(b'data')
        if case == 'running_change': current[0] = 'https://example.com/other'
        if case == 'cancel': controller.cancel(request.id())
        else:
            request.status = QWebEngineDownloadRequest.DownloadState.DownloadCompleted
            request.stateChanged.emit(request.status)
        assert destination.exists() is (case in {'complete', 'task_allowed'})
    else:
        assert not request.accepted and not destination.exists()
        if case != 'picker_change': assert not choices
    controller.close()
