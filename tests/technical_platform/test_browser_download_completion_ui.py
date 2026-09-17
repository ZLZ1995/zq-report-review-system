import os
import subprocess
import sys


def test_download_verification_waits_for_worker_and_checks_live_lease(tmp_path):
    code = r'''
import sys,time
from pathlib import Path
from threading import Event
from types import SimpleNamespace
from PySide6.QtCore import QTimer,QThread
from PySide6.QtWidgets import QApplication
from test_browser_download_integrity import delivered
from asset_based_agent.technical_platform.browser_download_completion_ui import verify_download_completion
from asset_based_agent.technical_platform.browser_download_completion_ui import DownloadCompletionDialog
from asset_based_agent.technical_platform import browser_download_integrity as integrity
app=QApplication([])
for case in ('accept','cancel','lease','decline'):
    path=Path(sys.argv[1])/case; path.mkdir()
    store,run,_,_,_=delivered(path)
    cancel=Event(); valid=[True]; finished=[]
    runtime=SimpleNamespace(lease=SimpleNamespace(binding=SimpleNamespace(owner=store.owner,task_id=run)),
        leases=SimpleNamespace(valid=lambda _:valid[0]),authorized=lambda:True)
    host=SimpleNamespace(store=store,run_id=run,cancel=cancel,runtime=runtime)
    original=integrity.verify_download_delivery
    def delayed(*args):
        assert QThread.currentThread()!=app.thread()
        try:
            time.sleep(.15)
            return original(*args)
        finally: finished.append(True)
    integrity.verify_download_delivery=delayed
    if case=='cancel': QTimer.singleShot(30,cancel.set)
    if case=='lease': QTimer.singleShot(30,lambda:valid.__setitem__(0,False))
    prompts=[]
    result=verify_download_completion(host,{'summary':'file delivered','evidence':'download'},
        confirm=lambda *args:prompts.append(True) or case!='decline')
    assert finished
    assert (result is not None)==(case=='accept')
    if result:
        import json
        from asset_based_agent.technical_platform.browser_task_host import BrowserTaskHost
        native_host=BrowserTaskHost(store,run,runtime_factory=lambda _:None,verify_completion=lambda _:result)
        native_host._running=True
        with store.connect() as db:
            native_host.claim_token=db.execute('SELECT claim_token FROM execution_steps WHERE run=?',(run,)).fetchone()[0]
        native_host._done('needs_verification',{'summary':'file delivered','evidence':'download'})
        assert store.run(run)['state']=='succeeded'
        dialog=DownloadCompletionDialog(json.loads(store.run(run)['snapshot']),
            {'summary':'<b>file</b>','evidence':'download','files':result['files']})
        assert not dialog.accept_button.isEnabled()
        assert dialog.reject_button.isDefault()
        assert 'file.txt' in dialog.details.toPlainText()
        assert '<b>file</b>' in dialog.details.toPlainText()
        assert result['files'][0]['sha256'] in dialog.details.toPlainText()
        dialog.deleteLater()
    if case in ('cancel','lease'): assert not prompts
    integrity.verify_download_delivery=original
'''
    env = dict(os.environ, QT_QPA_PLATFORM='offscreen')
    env['PYTHONPATH'] = os.pathsep.join(['src', 'tests/technical_platform', env.get('PYTHONPATH', '')])
    result = subprocess.run([sys.executable, '-X', 'utf8', '-c', code, str(tmp_path)],
                            env=env, capture_output=True, text=True, encoding='utf-8', timeout=30, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
