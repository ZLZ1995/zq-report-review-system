import os
import subprocess
import sys


def test_readonly_completion_requires_user_confirmation_and_rechecks(tmp_path):
    code = r'''
import json,sys
from pathlib import Path
from types import SimpleNamespace
from hashlib import sha256
from threading import Event
from PySide6.QtWidgets import QApplication
from test_browser_task_spec import make_browser_run
from asset_based_agent.browser_contracts import Observation
from asset_based_agent.technical_platform.browser_completion import verify_readonly_completion
app=QApplication([]); root=Path(sys.argv[1])
for case in ('accept','decline','write','cancel','changed','wrong_digest','wrong_owner','database_lost'):
    path=root/case; path.mkdir()
    store,run,_=make_browser_run(path,actions=['observe','navigate']+(['click'] if case=='write' else []))
    value=Observation(nonce='fresh',origin='https://example.com',text='Record alpha',controls=[],truncated=False,page_version=1)
    original=value
    class Observer:
        _epoch=1
        def observe(self,lease,callback): callback(value)
        def matches(self,lease,item): return item is value
    cancel=Event(); lease=SimpleNamespace(binding=SimpleNamespace(owner='alice',task_id=run))
    runtime=SimpleNamespace(completion_evidence={'origin':value.origin,'page_version':1,
        'evidence_sha256':sha256(b'Record alpha').hexdigest()},observer=Observer(),lease=lease,
        leases=SimpleNamespace(valid=lambda _:True),authorized=lambda:True)
    if case=='wrong_digest': runtime.completion_evidence['evidence_sha256']='0'*64
    if case=='wrong_owner': lease.binding.owner='bob'
    host=SimpleNamespace(store=store,run_id=run,runtime=runtime,cancel=cancel)
    calls=[]
    def confirm(snapshot,detail,active):
        global value
        calls.append(True)
        assert active()
        if case=='cancel': cancel.set()
        if case=='changed': value=original.model_copy(update={'text':'Record removed'})
        if case=='database_lost':
            import sqlite3
            from unittest.mock import patch
            from asset_based_agent.technical_platform.permissions import PermissionService
            with patch.object(PermissionService,'verify',side_effect=sqlite3.OperationalError('synthetic')):
                assert active() is False
            return False
        return case!='decline'
    proof=verify_readonly_completion(host,{'summary':'Found alpha','evidence':'Record alpha'},confirm=confirm)
    if case=='accept':
        assert proof['method']=='user_confirmed_readonly'
        assert proof['evidence_sha256']==sha256(b'Record alpha').hexdigest()
        assert proof['task_id']==run
    else: assert proof is None
    if case in ('write','wrong_digest','wrong_owner'): assert calls==[]
'''
    env=dict(os.environ,QT_QPA_PLATFORM='offscreen')
    env['PYTHONPATH']=os.pathsep.join(['src','tests/technical_platform',env.get('PYTHONPATH','')])
    result=subprocess.run([sys.executable,'-X','utf8','-c',code,str(tmp_path)],env=env,
        capture_output=True,text=True,encoding='utf-8',timeout=30,check=False)
    assert result.returncode==0,result.stdout+result.stderr


def test_completion_dialog_is_explicit_plain_text_and_expires_on_context_change(tmp_path):
    code = r'''
import json,sys
from pathlib import Path
from PySide6.QtCore import QTimer
from PySide6.QtGui import QFont,QFontDatabase
from PySide6.QtWidgets import QApplication
from test_browser_task_spec import make_browser_run
from asset_based_agent.technical_platform.browser_completion import CompletionDialog,confirm_readonly_result
app=QApplication([]); root=Path(sys.argv[1])
font=QFontDatabase.addApplicationFont('C:/Windows/Fonts/msyh.ttc')
app.setFont(QFont(QFontDatabase.applicationFontFamilies(font)[0],10))
store,run,_=make_browser_run(root,actions=['observe'])
snapshot=json.loads(store.run(run)['snapshot']); detail={'summary':'已找到指定公告 <img src=bad>','evidence':'公告编号 TEST-001'}
dialog=CompletionDialog(snapshot,detail)
assert not dialog.accept_button.isEnabled() and dialog.reject_button.isDefault()
assert '<img src=bad>' in dialog.details.toPlainText()
dialog.show(); app.processEvents(); dialog.grab().save(str(root/'completion.png')); dialog.close()
for mode in ('accept','decline','changed'):
    active=[True]
    def respond():
        dialog=app.activeModalWidget()
        assert isinstance(dialog,CompletionDialog)
        if mode=='changed': active[0]=False
        elif mode=='decline': dialog.reject_button.click()
        else:
            dialog.consent.setChecked(True); dialog.accept_button.click()
    QTimer.singleShot(50,respond)
    assert confirm_readonly_result(None,snapshot,detail,lambda:active[0]) is (mode=='accept')
'''
    env=dict(os.environ,QT_QPA_PLATFORM='offscreen')
    env['PYTHONPATH']=os.pathsep.join(['src','tests/technical_platform',env.get('PYTHONPATH','')])
    result=subprocess.run([sys.executable,'-X','utf8','-c',code,str(tmp_path)],env=env,
        capture_output=True,text=True,encoding='utf-8',timeout=20,check=False)
    assert result.returncode==0,result.stdout+result.stderr


def test_host_persists_bound_user_receipt_but_rejects_mismatch(tmp_path):
    code = r'''
import json,sys
from hashlib import sha256
from pathlib import Path
from PySide6.QtCore import QObject,Signal
from PySide6.QtWidgets import QApplication
from test_browser_task_spec import make_browser_run
from asset_based_agent.technical_platform.browser_task_host import BrowserTaskHost
from asset_based_agent.technical_platform.browser_task_spec import browser_execution_goal
from asset_based_agent.technical_platform.app import PlatformWindow
app=QApplication([]); root=Path(sys.argv[1])
class Runtime(QObject):
    progress=Signal(str); finished=Signal(str,object)
    def start(self): self.finished.emit('needs_verification',{'summary':'Found record','evidence':'Record alpha'})
for case in ('valid','wrong_task','wrong_summary','extra','write'):
    path=root/case; path.mkdir()
    store,run,project=make_browser_run(path,actions=['observe']+(['fill'] if case=='write' else []))
    snapshot=json.loads(store.run(run)['snapshot'])
    proof={'method':'user_confirmed_readonly','task_id':run,'origin':'https://example.com','page_version':1,
        'summary_sha256':sha256(b'Found record').hexdigest(),'evidence_sha256':sha256(b'Record alpha').hexdigest(),
        'goal_sha256':sha256(browser_execution_goal(snapshot).encode()).hexdigest(),'confirmed_at':'test'}
    if case=='wrong_task': proof['task_id']='wrong'
    if case=='wrong_summary': proof['summary_sha256']='0'*64
    if case=='extra': proof['unsafe_metadata']='not allowed'
    window=PlatformWindow(store); window.project_id=project; window.session_id=store.run(run)['session']; window.run_id=run
    host=BrowserTaskHost(store,run,window,runtime_factory=lambda host:Runtime(host),verify_completion=lambda _:proof)
    window.register_task_worker(host); host.start(); app.processEvents()
    record=store.run(run); result=json.loads(record['result'])
    if case=='valid':
        assert record['state']=='succeeded' and result['verification']==proof
        assert any('已由你核对确认' in m['text'] for m in store.messages(window.session_id))
    else:
        assert record['state']=='failed' and result['verified'] is False and 'verification' not in result
    window.close(); app.processEvents()
'''
    env=dict(os.environ,QT_QPA_PLATFORM='offscreen')
    env['PYTHONPATH']=os.pathsep.join(['src','tests/technical_platform',env.get('PYTHONPATH','')])
    result=subprocess.run([sys.executable,'-X','utf8','-c',code,str(tmp_path)],env=env,
        capture_output=True,text=True,encoding='utf-8',timeout=30,check=False)
    assert result.returncode==0,result.stdout+result.stderr
