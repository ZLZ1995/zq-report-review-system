import os
import subprocess
import sys


def test_login_scripts_real_dom_revalidation_and_no_submit(tmp_path):
    code = r'''
import json, sys, time
from pathlib import Path
from PySide6.QtCore import QUrl
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile
from asset_based_agent.technical_platform.browser_login_scripts import probe_script, fill_script
root=Path(sys.argv[1]); app=QApplication([])
profile=QWebEngineProfile('synthetic-login')
profile.setPersistentStoragePath(str(root/'profile')); profile.setCachePath(str(root/'cache'))
page=QWebEnginePage(profile)
def until(predicate):
    end=time.monotonic()+10
    while not predicate() and time.monotonic()<end: QTest.qWait(10)
    assert predicate(), 'Synthetic DOM callback timed out'
def js(script, world=1):
    results=[]; page.runJavaScript(script,world,results.append)
    until(lambda: bool(results)); return results[0]
# In-memory fixture with HTTPS base origin, not a TLS acceptance test.
loaded=[]; page.loadFinished.connect(loaded.append)
page.setHtml('<form action="/login" method="post"><input id="u" autocomplete="username">'
             '<input id="p" type="password"><button>Login</button></form>',QUrl('https://fixture.invalid/'))
until(lambda: loaded and loaded[-1])
probe=json.loads(js(probe_script('first')))
assert probe['ok'] and probe['origin']=='https://fixture.invalid', probe
assert set(probe)=={'ok','origin','action','nonce'}
js("document.querySelector('form').action='https://other.invalid/login'",0)
assert not json.loads(js(fill_script('first','https://fixture.invalid','synthetic-user','synthetic-password')))['ok']
assert js("document.getElementById('p').value",0)==''
js("document.querySelector('form').action='/login'",0)
assert json.loads(js(probe_script('second')))['ok']
js("document.getElementById('u').value='user-edited'",0)
assert not json.loads(js(fill_script('second','https://fixture.invalid','synthetic-user','synthetic-password')))['ok']
assert js("document.getElementById('p').value",0)==''
assert json.loads(js(probe_script('third')))['ok']
js("window.submissions=0; document.querySelector('form').addEventListener('submit', e=>{e.preventDefault();window.submissions++})",0)
assert json.loads(js(fill_script('third','https://fixture.invalid','synthetic-user','synthetic-password'))) == {'ok':True}
assert js("document.getElementById('u').value",0)=='synthetic-user'
assert js("document.getElementById('p').value",0)=='synthetic-password'
assert js('window.submissions',0)==0
assert not json.loads(js(fill_script('third','https://fixture.invalid','x','y')))['ok'], 'Ticket reused'
assert js('typeof globalThis.__zqLoginProbe',0)=='undefined', 'State leaked to page world'
js("document.querySelector('form').id='login-form'; const b=document.createElement('button'); b.setAttribute('form','login-form'); b.setAttribute('formaction','https://other.invalid'); document.body.appendChild(b)",0)
assert not json.loads(js(probe_script('external-submit')))['ok']
js("document.querySelector('button[form]').remove()",0)
from types import SimpleNamespace
from asset_based_agent.technical_platform.storage_preferences import StoragePreferences
from asset_based_agent.technical_platform.browser_credential_vault import CredentialVault
from asset_based_agent.technical_platform.browser_trusted_login import TrustedLogin
(root/'program').mkdir(); (root/'data').mkdir()
prefs=StoragePreferences(root/'index.sqlite',root/'program'); prefs.select('alice',root/'data')
vault=CredentialVault(prefs,'alice',environment='test')
key=vault.save('https://fixture.invalid','stored-user','stored-password',confirmed=True,login_succeeded=True)
session=SimpleNamespace(owner='alice',environment='test',preferences=prefs,owns_page=lambda p:p is page)
bridge=TrustedLogin(session,page,vault)
tickets=[]; bridge.probe(tickets.append); until(lambda: bool(tickets))
assert tickets[0] is not None
filled=[]; bridge.fill(tickets[0],key,confirmed=True,callback=filled.append)
until(lambda: bool(filled)); assert filled==[True]
assert js("document.getElementById('p').value",0)=='stored-password'
assert js('window.submissions',0)==0
from asset_based_agent.technical_platform.browser_task_permissions import BrowserTaskPermissions, LoginScope
from asset_based_agent.technical_platform.execution_contracts import TaskIdentity
permissions=BrowserTaskPermissions(); task_state=[None]
task_bridge=TrustedLogin(session,page,vault,tab_id='task-tab',task_permissions=permissions,
                         task_scope=lambda:task_state[0])
def task_fill():
    tickets=[]; task_bridge.probe(tickets.append); until(lambda: bool(tickets))
    assert tickets[0] is not None
    task_state[0]=LoginScope(identity=TaskIdentity(owner='alice',project_id='p',session_id='s',task_id='t',request_id='r'),
        environment='test',revision=1,step_id='login',tab_id='task-tab',page_version=task_bridge.page_version,
        origin='https://fixture.invalid',credential_id=key)
    permit=permissions.authorize_login(task_state[0],confirmed=True)
    result=[]; task_bridge.fill_for_task(tickets[0],permit,callback=result.append)
    until(lambda: bool(result)); return result
js("document.getElementById('u').value='';document.getElementById('p').value=''",0)
assert task_fill()==[False], 'Saved password is not Agent consent'
assert js("document.getElementById('p').value",0)==''
vault.set_agent_access(key,True,confirmed=True)
assert task_fill()==[True]
assert js("document.getElementById('p').value",0)=='stored-password'
assert js('window.submissions',0)==0
vault.set_agent_access(key,False,confirmed=True)
js("document.getElementById('u').value='';document.getElementById('p').value=''",0)
assert task_fill()==[False]
assert js("document.getElementById('p').value",0)==''
task_bridge.close(); permissions.close()
from PySide6.QtWidgets import QWidget, QInputDialog
from PySide6.QtCore import QTimer
from asset_based_agent.technical_platform.browser_login_actions import BrowserLoginActions
class Host(QWidget):
    def __init__(self):
        super().__init__(); self.session=session
        self.view=SimpleNamespace(page=lambda:page); self.messages=[]
    def current_view(self): return self.view
    def notice(self, view, message): self.messages.append(message)
host=Host(); host.show(); actions=BrowserLoginActions(host)
js("document.getElementById('u').value='';document.getElementById('p').value=''",0)
def accept_dialog():
    dialog=QApplication.activeModalWidget()
    if not isinstance(dialog,QInputDialog):
        QTimer.singleShot(10,accept_dialog); return
    assert 'https://fixture.invalid' in dialog.labelText()
    assert 'stored-password' not in dialog.labelText()
    dialog.grab().save(str(root/'fill-confirmation.png'))
    dialog.accept()
QTimer.singleShot(10,accept_dialog)
actions.fill_current()
until(lambda: any('已填入' in m for m in host.messages))
assert js("document.getElementById('p').value",0)=='stored-password'
assert js('window.submissions',0)==0
js("document.getElementById('u').value='';document.getElementById('p').value=''",0)
def cancel_dialog():
    if not isinstance(QApplication.activeModalWidget(),QInputDialog):
        QTimer.singleShot(10,cancel_dialog); return
    actions.cancel()
QTimer.singleShot(10,cancel_dialog)
actions.fill_current()
until(lambda: actions.dialog is None and actions.active is None)
assert js("document.getElementById('p').value",0)==''
actions.cancel(); host.close()
import shiboken6
shiboken6.delete(page); shiboken6.delete(profile)
print('login-dom: ok')
'''
    result = subprocess.run([sys.executable, '-X', 'utf8', '-c', code, str(tmp_path)],
                            env=os.environ.copy(), capture_output=True, text=True,
                            timeout=60, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'login-dom: ok' in result.stdout
