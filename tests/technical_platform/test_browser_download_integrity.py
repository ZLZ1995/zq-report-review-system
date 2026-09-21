import json
from threading import Event

import pytest
from test_browser_download_artifacts import ready


def delivered(tmp_path, *, actions=None):
    from asset_based_agent.technical_platform.browser_download_artifacts import (
        DownloadArtifacts,
        fingerprint_download,
    )
    store, run, request, receipt, path, url, service = ready(tmp_path, 'https://example.com/project', actions=actions)
    service.consume_browser_action(receipt, request)
    fingerprint = fingerprint_download(path, path.stat().st_size, Event())
    identity = DownloadArtifacts(store).save(request, receipt, url, fingerprint,
                                            source_url='https://example.com/project')
    return store, run, path, identity, service


def test_download_integrity_manifest_is_native_and_contains_no_paths(tmp_path):
    from asset_based_agent.technical_platform.browser_download_integrity import (
        verify_download_delivery,
    )
    store, run, path, identity, _ = delivered(tmp_path)
    manifest = verify_download_delivery(store, run, Event())
    assert manifest['task_id'] == run
    assert len(manifest['goal_sha256']) == 64
    assert manifest['files'][0]['id'] == identity
    assert manifest['files'][0]['origin'] == 'https://example.com'
    assert manifest['files'][0]['size'] == path.stat().st_size
    assert str(path) not in json.dumps(manifest)
    assert not ({'verified', 'succeeded', 'method'} & set(manifest))


def test_native_saved_credential_fill_scope_does_not_block_download_delivery(tmp_path):
    from asset_based_agent.technical_platform.browser_download_completion import (
        confirm_download_delivery,
    )
    from asset_based_agent.technical_platform.browser_download_integrity import (
        verify_download_delivery,
    )
    store, run, _, _, _ = delivered(tmp_path, actions=['observe', 'download', 'login'])
    cancel = Event()
    manifest = verify_download_delivery(store, run, cancel)
    receipt = confirm_download_delivery(store, run, cancel, manifest,
        {'summary': 'Requested file delivered', 'evidence': 'File download'},
        confirm=lambda *_: True, is_current=lambda: True)
    assert receipt['method'] == 'user_confirmed_download'
    assert 'login_succeeded' not in receipt


@pytest.mark.parametrize('action', ['click', 'fill', 'select', 'upload'])
def test_download_receipt_does_not_complete_authorized_business_write_scope(tmp_path, action):
    from asset_based_agent.technical_platform.browser_download_integrity import (
        verify_download_delivery,
    )
    store, run, _, _, _ = delivered(tmp_path, actions=['observe', 'download', action])
    with pytest.raises(PermissionError, match='download-only'):
        verify_download_delivery(store, run, Event())


@pytest.mark.parametrize('case', ['replaced', 'cancelled', 'revoked', 'missing', 'other_owner', 'write_scope'])
def test_download_integrity_rejects_invalid_context(tmp_path, case):
    from asset_based_agent.technical_platform.browser_download_integrity import (
        verify_download_delivery,
    )
    from asset_based_agent.technical_platform.store import PlatformStore
    store, run, path, _, service = delivered(tmp_path)
    cancel=Event()
    if case == 'replaced': path.write_bytes(b'changed')
    if case == 'missing': path.unlink()
    if case == 'cancelled': cancel.set()
    if case == 'revoked': service.revoke(run)
    if case == 'other_owner': store=PlatformStore(store.path, 'other')
    if case == 'write_scope':
        with store.connect() as db:
            snapshot=json.loads(store.run(run)['snapshot'])
            snapshot['browser_scope']['actions'].append('upload')
            db.execute('UPDATE runs SET snapshot=? WHERE id=?', (json.dumps(snapshot),run))
    with pytest.raises((ValueError, OSError, PermissionError)):
        verify_download_delivery(store, run, cancel)


def test_download_integrity_checks_revocation_after_read(tmp_path, monkeypatch):
    from asset_based_agent.technical_platform import (
        browser_download_integrity as module,
    )
    store, run, _, _, service = delivered(tmp_path)
    original=module.fingerprint_download
    def revoke(*args):
        result=original(*args)
        service.revoke(run)
        return result
    monkeypatch.setattr(module, 'fingerprint_download', revoke)
    with pytest.raises(PermissionError): module.verify_download_delivery(store, run, Event())


def test_download_integrity_detects_change_after_hash(tmp_path, monkeypatch):
    from asset_based_agent.technical_platform import (
        browser_download_integrity as module,
    )
    store, run, path, _, _ = delivered(tmp_path)
    original=module.fingerprint_download
    def mutate(*args):
        result=original(*args)
        path.write_bytes(b'replaced-after-hash')
        return result
    monkeypatch.setattr(module, 'fingerprint_download', mutate)
    with pytest.raises(ValueError): module.verify_download_delivery(store, run, Event())


def test_download_delivery_worker_uses_background_thread_and_contains_errors(tmp_path):
    import os
    import subprocess
    import sys
    code=r'''
import sys,time
from pathlib import Path
from threading import Event
from PySide6.QtCore import QCoreApplication,QThread
from PySide6.QtTest import QTest
from test_browser_download_integrity import delivered
from asset_based_agent.technical_platform import browser_download_integrity as module
from asset_based_agent.technical_platform.browser_download_worker import DownloadDeliveryWorker
app=QCoreApplication([])
store,run,path,identity,_=delivered(Path(sys.argv[1]))
original=module.verify_download_delivery
def checked(*args):
    assert QThread.currentThread()!=app.thread()
    return original(*args)
module.verify_download_delivery=checked
for cancelled in (False,True):
    cancel=Event()
    if cancelled: cancel.set()
    worker=DownloadDeliveryWorker(store,run,cancel)
    worker.start()
    deadline=time.monotonic()+10
    while worker.isRunning() and time.monotonic()<deadline: QTest.qWait(10)
    assert not worker.isRunning()
    if cancelled: assert worker.result is None
    else: assert worker.result['files'][0]['id']==identity
    worker.deleteLater(); app.processEvents()
'''
    env=dict(os.environ, QT_QPA_PLATFORM='offscreen')
    env['PYTHONPATH']=os.pathsep.join(['src','tests/technical_platform',env.get('PYTHONPATH','')])
    result=subprocess.run([sys.executable,'-X','utf8','-c',code,str(tmp_path)],env=env,
                          capture_output=True,text=True,encoding='utf-8',timeout=25,check=False)
    assert result.returncode==0,result.stdout+result.stderr
