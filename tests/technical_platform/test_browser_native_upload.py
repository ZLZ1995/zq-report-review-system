import json
import os
from threading import Event
from types import SimpleNamespace

import pytest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtCore import QUrl
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from test_browser_upload_authorization import ready


@pytest.mark.parametrize('case', ['success', 'refuse', 'page_changed', 'cancel', 'revoked', 'start_failed'])
def test_native_upload_connects_worker_receipt_and_transfer(tmp_path, case, monkeypatch):
    from asset_based_agent.technical_platform.browser_native_upload import (
        NativeTaskUpload,
    )
    app = QApplication.instance() or QApplication([])
    assert app is not None
    store, run, scope, reference = ready(tmp_path)
    calls = []
    class Page:
        def url(self): return QUrl('https://example.com/upload')
        def isLoading(self): return False
        def runJavaScript(self, script, world, callback=None):
            args = json.loads(script.rsplit('})(', 1)[1][:-1]); calls.append(args['op'])
            status = {'begin': 'ready', 'chunk': 'ready', 'finish': 'verifying',
                'status': 'verified', 'commit': 'dispatched', 'abort': 'rejected'}[args['op']]
            if args['op'] == 'status' and case == 'revoked':
                from asset_based_agent.technical_platform.permissions import (
                    PermissionService,
                )
                PermissionService(store).revoke(run)
            if callback: callback(json.dumps({'status': status}))
    observer = SimpleNamespace(_epoch=1, _nonce='nonce', matches=lambda *_: True,
                               reserve_upload=lambda *_: True)
    host = SimpleNamespace(store=store, cancel=Event(), claim_token=scope.claim_token,
        plan=SimpleNamespace(revision=1, steps=[SimpleNamespace(step_id=scope.step_id)]))
    native = SimpleNamespace(host=host, page=Page(), identity=scope.identity,
        lease=SimpleNamespace(tab_id='tab'), scope=SimpleNamespace(environment='test'),
        allowed=lambda *_: not host.cancel.is_set())
    observation = SimpleNamespace(origin='https://example.com', page_version=1, nonce='nonce')
    from asset_based_agent.browser_contracts import BrowserStepProposal
    metadata = {'id':'artifact-1','name':scope.artifact.name,'size':scope.artifact.size,
                'sha256':scope.artifact.sha256}
    confirmations = []
    def confirm(observed, proposal, artifact, valid):
        confirmations.append(artifact)
        assert valid() and artifact == metadata
        return case != 'refuse'
    upload = NativeTaskUpload(native, observer, artifacts=[{'artifact':metadata,'source':reference}],
                              confirm_upload=confirm)
    assert upload.candidates() == [metadata]
    done = []
    if case == 'start_failed':
        from asset_based_agent.technical_platform.browser_upload_worker import (
            UploadPreparationWorker,
        )
        def fail_start(self):
            raise RuntimeError('Synthetic thread startup failure')
        monkeypatch.setattr(UploadPreparationWorker, 'start', fail_start)
    upload.request(observation, BrowserStepProposal(request_id='request',action='upload',target='1',
        artifact_id='artifact-1',object_label='Synthetic project 001',summary='Upload'), done.append)
    if case == 'page_changed': observer._epoch += 1
    if case == 'cancel': upload.close()
    for _ in range(1 if case == 'start_failed' else 1500):
        if done: break
        QTest.qWait(10)
    assert done == (['dispatched'] if case == 'success' else
                    ['unknown'] if case == 'revoked' else
                    ['rejected'] if case in {'refuse', 'start_failed'} else ['cancelled']), (calls, upload.terminal, upload.worker is not None)
    assert calls.count('commit') == (1 if case == 'success' else 0)
    assert not upload.isRunning()
    with store.connect() as db:
        consumed = db.execute('SELECT COUNT(*) FROM browser_action_authorizations '
                              'WHERE run=? AND consumed=1', (run,)).fetchone()[0]
    assert consumed == (1 if case == 'success' else 0)
    if case in {'success', 'revoked'}:
        assert upload.candidates() == []
        repeated = []
        before = len(confirmations)
        upload.request(observation, BrowserStepProposal(request_id='again',action='upload',target='1',
            artifact_id='artifact-1',object_label='Synthetic project 001',summary='Repeat'), repeated.append)
        assert repeated == ['rejected'] and len(confirmations) == before
    upload.close(); upload.deleteLater()
