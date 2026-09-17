"""Synthetic local-page integration probe; no external upload or model call."""
import json
import os
import sys
import time
from pathlib import Path
from threading import Event
from types import SimpleNamespace

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
repository = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(repository / 'src'), str(repository / 'tests' / 'technical_platform')]

from PySide6.QtCore import QUrl
from PySide6.QtTest import QTest
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QApplication
from test_browser_upload_authorization import ready

from asset_based_agent.browser_contracts import BrowserStepProposal
from asset_based_agent.technical_platform.browser_native_upload import NativeTaskUpload
from asset_based_agent.technical_platform.browser_observer import BrowserObserver

root = Path(sys.argv[1])
root.mkdir(parents=True, exist_ok=True)
app = QApplication([])
store, run, scope, reference = ready(root)
profile = QWebEngineProfile('synthetic-upload')
profile.setPersistentStoragePath(str(root / 'profile'))
profile.setCachePath(str(root / 'cache'))
page = QWebEnginePage(profile)
view = QWebEngineView(page); view.resize(900, 700); view.show()
loaded = []
page.loadFinished.connect(loaded.append)
page.setHtml('<form method=post action=/upload><label for=f>Artifact</label><input type=file id=f></form>'
    '<script>window.changed=0;document.getElementById("f").addEventListener("change",async e=>{'
    'window.changed++;window.body=await e.target.files[0].text();});</script>', QUrl('https://example.com/upload'))

def until(check):
    deadline = time.monotonic() + 20
    while not check() and time.monotonic() < deadline:
        QTest.qWait(10)
    assert check(), 'Probe timed out'

def js(script):
    result = []
    page.runJavaScript(script, 0, result.append)
    until(lambda: bool(result))
    return result[0]

until(lambda: bool(loaded))
lease = SimpleNamespace(tab_id='tab')
leases = SimpleNamespace(tab_id=lambda p: 'tab', valid=lambda _: True,
                         session=SimpleNamespace(owns_page=lambda p: p is page))
observer = BrowserObserver(leases, page, can_observe=lambda *_: True, can_upload=lambda *_: True)
observed = []
observer.observe(lease, observed.append)
until(lambda: bool(observed))
observation = observed[0]
assert observation is not None
target = next(c.id for c in observation.controls if c.kind == 'file')
host = SimpleNamespace(store=store, cancel=Event(), claim_token=scope.claim_token,
    plan=SimpleNamespace(revision=1, steps=[SimpleNamespace(step_id=scope.step_id)]))
native = SimpleNamespace(host=host, page=page, identity=scope.identity, lease=lease,
    scope=SimpleNamespace(environment='test'), allowed=lambda *_: not host.cancel.is_set())
metadata = {'id': 'artifact', 'name': scope.artifact.name, 'size': scope.artifact.size,
            'sha256': scope.artifact.sha256}
confirmations = []
def confirm(obs, proposal, artifact, valid):
    confirmations.append(artifact)
    return valid()
upload = NativeTaskUpload(native, observer, artifacts=[{'artifact': metadata, 'source': reference}],
                          confirm_upload=confirm)
proposal = BrowserStepProposal(request_id='probe', action='upload', target=target,
    artifact_id='artifact', object_label='Synthetic project', summary='Synthetic probe')
done = []
upload.request(observation, proposal, done.append)
until(lambda: bool(done))
assert done == ['dispatched'], done
until(lambda: js('window.body') is not None)
assert js('window.body') == 'synthetic artifact, not a business document'
assert js('window.changed') == 1
assert js('typeof globalThis.__zqUpload') == 'undefined'
with store.connect() as db:
    assert db.execute('SELECT COUNT(*) FROM browser_action_authorizations WHERE consumed=1').fetchone()[0] == 1
assert upload.candidates() == [] and not upload.isRunning()
repeated = []
upload.request(observation, proposal, repeated.append)
assert repeated == ['rejected'] and len(confirmations) == 1
upload.close(); observer.close()
import shiboken6

shiboken6.delete(upload); shiboken6.delete(view); shiboken6.delete(page); shiboken6.delete(profile)
print(json.dumps({'status': 'passed', 'root': str(root), 'dispatch_count': 1,
                  'real_webengine': True, 'real_sqlite': True, 'external_upload': False}))
