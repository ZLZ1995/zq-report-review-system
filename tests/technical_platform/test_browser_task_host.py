import os
import subprocess
import sys


def test_browser_host_uses_window_registry_and_persists_verified_outcome(tmp_path):
    code = r'''
import json, sys
from pathlib import Path
from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtWidgets import QApplication
from test_browser_task_spec import make_browser_run
from asset_based_agent.technical_platform.app import PlatformWindow
from asset_based_agent.technical_platform.browser_task_host import BrowserTaskHost
app=QApplication([])
root=Path(sys.argv[1])
class Runtime(QObject):
    progress=Signal(str)
    finished=Signal(str,object)
    def __init__(self, parent, status):
        super().__init__(parent); self.status=status
    def start(self):
        QTimer.singleShot(0, lambda:self.finished.emit(self.status,
            {'summary':'Synthetic result', 'evidence':'Synthetic receipt'}))
for status, approved, expected in [('needs_verification',False,'failed'),
                                  ('needs_verification',True,'failed'),
                                  ('needs_input',False,'failed'),
                                  ('unknown',False,'failed'),('cancelled',False,'cancelled')]:
    case=root/(status+str(approved)); case.mkdir()
    store, run, project=make_browser_run(case)
    window=PlatformWindow(store)
    window.project_id=project; window.session_id=store.run(run)['session']; window.run_id=run
    worker=BrowserTaskHost(store,run,window,
        runtime_factory=lambda host:Runtime(host,status), verify_completion=lambda detail:approved)
    window.register_task_worker(worker)
    worker.start()
    for _ in range(20): app.processEvents()
    assert not window.task_manager.active()
    record=store.run(run)
    assert record['state']==expected
    result=json.loads(record['result'])
    assert result['kind']=='browser'
    assert result['verified'] is False  # A boolean is not a bound business receipt.
    if status in ('needs_input','needs_verification'):
        assert result['summary']=='Synthetic result'
        assert result['evidence']=='Synthetic receipt'
    with store.connect() as db:
        steps=db.execute('SELECT state FROM execution_steps WHERE run=?',(run,)).fetchall()
        assert steps[0][0]==('unknown' if status=='unknown' else expected)
    texts=[m['text'] for m in store.messages(window.session_id)]
    assert any('浏览器' in text for text in texts)
    assert not any('资料预检完成' in text for text in texts)
    if status in ('needs_input','needs_verification'):
        assert any('Synthetic result' in text for text in texts)
    window.close(); app.processEvents()
# Cancellation or revoked consent during a native verifier cannot become success.
for mode in ('cancel', 'revoke', 'unconfirmed', 'double-start'):
    case=root/mode; case.mkdir()
    store, run, project=make_browser_run(case, authorize=mode!='unconfirmed')
    from asset_based_agent.technical_platform.permissions import PermissionService
    calls=[]
    def verify(detail):
        if mode=='cancel': worker.cancel.set()
        if mode=='revoke':
            with store.connect() as db:
                db.execute('UPDATE execution_authorizations SET revoked=1 WHERE run=?',(run,))
        return True
    def factory(host):
        calls.append(True)
        return Runtime(host,'needs_verification')
    worker=BrowserTaskHost(store,run,runtime_factory=factory,verify_completion=verify)
    worker.start(); worker.start()
    for _ in range(20): app.processEvents()
    record=store.run(run)
    assert not worker.isRunning()
    if mode=='unconfirmed':
        assert calls==[] and record['state']=='queued'
    else:
        assert len(calls)==1
        assert record['state']=={'cancel':'cancelled','revoke':'failed','double-start':'failed'}[mode]
        assert json.loads(record['result'])['verified'] is False
print('browser task host: ok')
'''
    env = dict(os.environ, QT_QPA_PLATFORM='offscreen')
    env['PYTHONPATH'] = os.pathsep.join(['src', 'tests/technical_platform', env.get('PYTHONPATH', '')])
    result = subprocess.run([sys.executable, '-X', 'utf8', '-c', code, str(tmp_path)], env=env,
                            capture_output=True, text=True, encoding='utf-8', timeout=45, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
