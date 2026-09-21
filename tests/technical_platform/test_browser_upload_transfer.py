import json
import os
from types import SimpleNamespace

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication


def test_transfer_checks_authority_after_verification_and_never_replays():
    from asset_based_agent.technical_platform.browser_upload_transfer import (
        UploadTransfer,
    )
    app = QApplication.instance() or QApplication([])
    assert app is not None
    for revoke in (False, True):
        active = [True]
        calls, consumed, finished = [], [], []
        class Page:
            def runJavaScript(self, script, world, callback=None, calls=calls, revoke=revoke, active=active):
                assert world == 1
                args = json.loads(script.rsplit('})(', 1)[1][:-1])
                calls.append(args['op'])
                status = {'begin': 'ready', 'chunk': 'ready', 'finish': 'verifying',
                          'status': 'verified', 'commit': 'dispatched', 'abort': 'rejected'}[args['op']]
                if args['op'] == 'status' and revoke:
                    active[0] = False
                if callback:
                    callback(json.dumps({'status': status}))
                    callback(json.dumps({'status': status}))  # Late/duplicate delivery.
        artifact = SimpleNamespace(name='test.txt', size=3, sha256='a' * 64)
        scope = SimpleNamespace(origin='https://example.com', field_id='1', artifact=artifact)
        permit = SimpleNamespace(key='token', scope=scope)
        transfer = UploadTransfer(Page(), permit, 'nonce', b'syn',
            active=lambda active=active: active[0], commit=lambda consumed=consumed: consumed.append(True))
        transfer.finished.connect(finished.append)
        transfer.start()
        for _ in range(100):
            if finished: break
            QTest.qWait(10)
        assert finished == (['cancelled'] if revoke else ['dispatched'])
        assert calls.count('commit') == (0 if revoke else 1)
        assert consumed == ([] if revoke else [True])
        transfer.close()
        assert len(finished) == 1
        transfer.deleteLater()
