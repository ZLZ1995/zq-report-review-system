import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QUrl
from PySide6.QtWebEngineCore import QWebEngineDownloadRequest
from test_browser_task_downloads import task_controller


@pytest.mark.parametrize('case', ['complete', 'denied', 'changed', 'foreign'])
def test_button_download_arms_before_dispatch_and_binds_actual_resource(tmp_path, case):
    from asset_based_agent.technical_platform.browser_native_download import (
        NativeTaskDownload,
    )
    controller, request, destination, page = task_controller(tmp_path)
    page.url = lambda: QUrl('https://example.com/page')
    page.isLoading = lambda: False
    active = [True]; results = []; receipts = []
    url = 'blob:https://example.com/12345678-1234-1234-1234-123456789abc'
    if case == 'foreign': url = url.replace('example.com', 'other.test')
    request.url = lambda: QUrl(url)
    def dispatch(*args, callback, before_dispatch):
        assert id(page) not in controller._armed
        if case == 'denied':
            callback('rejected'); return
        assert before_dispatch()
        assert id(page) in controller._armed
        if case == 'changed': active[0] = False
        controller.request(request)
        callback('dispatched')
    observer = SimpleNamespace(_epoch=1, matches=lambda *_: True, download_button=dispatch)
    native = SimpleNamespace(page=page, lease=object(), identity=SimpleNamespace(task_id='task-one'),
        allowed=lambda *_: active[0], request=lambda **values: values,
        service=SimpleNamespace(authorize_browser_action=lambda value,confirmed: receipts.append(value) or 'receipt',
                                consume_browser_action=lambda *_: None))
    adapter = NativeTaskDownload(native, observer, controller)
    observation = SimpleNamespace(page_version=1, controls=[SimpleNamespace(id='1',kind='button')])
    adapter.begin(observation, '1', lambda status, record: results.append((status,record)))
    if case == 'complete':
        assert request.accepted
        (Path(request.directory)/request.filename).write_bytes(b'data')
        request.status=QWebEngineDownloadRequest.DownloadState.DownloadCompleted
        request.stateChanged.emit(request.status)
        assert results[0][0]=='downloaded'
        assert json.loads(receipts[0]['payload'])['url']==url
    else:
        assert not request.accepted and not destination.exists()
        assert len(results)==1 and results[0][0] in {'rejected','unknown'}
    adapter.close(); controller.close()


@pytest.mark.parametrize('case',['complete','cancel','changed','wrong_url'])
def test_native_download_waits_for_actual_delivery_and_binds_destination(tmp_path,case):
    from asset_based_agent.technical_platform.browser_native_download import (
        NativeTaskDownload,
    )
    controller,request,destination,page=task_controller(tmp_path)
    calls=[]; receipts=[]; active=[True]
    page.url=lambda:QUrl('https://example.com/page')
    page.isLoading=lambda:False
    page.download=lambda url:calls.append(url.toString())
    observer=SimpleNamespace(_epoch=1,matches=lambda *_:True,
        resolve_download=lambda *args,callback:callback('https://example.com/file'))
    native=SimpleNamespace(page=page,lease=object(),identity=SimpleNamespace(task_id='task-one'),
        allowed=lambda action,url:action=='download' and url.startswith('https://example.com') and active[0],
        request=lambda **values:values,
        service=SimpleNamespace(authorize_browser_action=lambda req,confirmed:receipts.append(req) or 'receipt',
                                consume_browser_action=lambda *_:None))
    adapter=NativeTaskDownload(native,observer,controller)
    results=[]
    adapter.begin(SimpleNamespace(page_version=1), '1', lambda status,record:results.append((status,record)))
    assert calls==['https://example.com/file'] and not results
    if case=='cancel': adapter.close()
    if case=='changed': observer._epoch=2
    if case=='wrong_url': request.url=lambda:QUrl('https://example.com/other')
    controller.request(request)
    if case=='complete':
        assert request.accepted and not results
        (Path(request.directory)/request.filename).write_bytes(b'data')
        request.status=QWebEngineDownloadRequest.DownloadState.DownloadCompleted
        request.stateChanged.emit(request.status)
        assert results[0][0]=='downloaded'
        assert results[0][1]['path']==str(destination) and results[0][1]['size']==4
        assert json.loads(receipts[0]['payload'])['destination']==str(destination)
    else:
        assert not request.accepted and not destination.exists()
        assert results[0][0] in {'cancelled','rejected'} and results[0][1] is None
    assert len(results)==1
    adapter.close(); controller.close()
