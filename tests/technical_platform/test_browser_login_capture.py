import os
import subprocess
import sys


def test_real_isolated_capture_and_lifecycle(tmp_path):
    code = r'''
import json, sys, time
from pathlib import Path
from types import SimpleNamespace
from PySide6.QtCore import QUrl, Qt, QPoint
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from PySide6.QtWebEngineCore import QWebEngineProfile, QWebEnginePage
from PySide6.QtWebEngineWidgets import QWebEngineView
from asset_based_agent.technical_platform.browser_login_capture import LoginCapture
from asset_based_agent.technical_platform.storage_preferences import StoragePreferences
from asset_based_agent.technical_platform.browser_credential_vault import CredentialVault
root=Path(sys.argv[1]); app=QApplication([])
(root/'program').mkdir(); (root/'data').mkdir()
prefs=StoragePreferences(root/'index.sqlite',root/'program'); prefs.select('alice',root/'data')
vault=CredentialVault(prefs,'alice',environment='test')
profile=QWebEngineProfile('capture-test')
profile.setPersistentStoragePath(str(root/'profile')); profile.setCachePath(str(root/'cache'))
page=QWebEnginePage(profile); view=QWebEngineView(page); view.resize(600,400); view.show()
session=SimpleNamespace(owner='alice',environment='test',preferences=prefs,owns_page=lambda p:p is page)
capture=LoginCapture(session,page,vault)
def until(predicate):
    end=time.monotonic()+10
    while not predicate() and time.monotonic()<end: QTest.qWait(10)
    assert predicate(), 'Capture test timed out'
def js(script, world=0):
    out=[]; page.runJavaScript(script,world,out.append); until(lambda: bool(out)); return out[0]
loaded=[]; page.loadFinished.connect(loaded.append)
def load():
    loaded.clear()
    page.setHtml('<form method="post" action="/login" onsubmit="event.preventDefault()">'
                 '<input id="u" autocomplete="username" value="synthetic-user">'
                 '<input id="p" type="password" value="synthetic-pass">'
                 '<button id="b">Login</button></form>',QUrl('https://fixture.invalid/'))
    until(lambda: loaded and loaded[-1]); until(lambda: capture.armed)
def click():
    point=json.loads(js("JSON.stringify((()=>{let r=document.getElementById('b').getBoundingClientRect();return [r.x+r.width/2,r.y+r.height/2]})())"))
    QTest.mouseClick(view.focusProxy(),Qt.MouseButton.LeftButton,Qt.KeyboardModifier.NoModifier,QPoint(int(point[0]),int(point[1])))
    QTest.qWait(100)
load()
assert js('typeof qt')=='undefined', 'Native transport exposed to page world'
assert not vault.path.exists()
js("document.querySelector('form').dispatchEvent(new Event('submit',{bubbles:true,cancelable:true}))")
QTest.qWait(100); assert capture.pending is None
js("document.querySelector('form').action='https://other.invalid'")
click(); assert capture.pending is None
js("document.querySelector('form').action='/login'")
click(); until(lambda: capture.pending is not None)
assert vault.entries()==[], 'Captured credential persisted before consent'
assert b'synthetic-pass' not in vault.path.read_bytes()
assert 'synthetic-pass' not in repr(capture.pending)
# Local UI explicitly confirms success. Navigation alone never saves.
from asset_based_agent.technical_platform.browser_login_save_prompt import LoginSavePrompt
prompt=LoginSavePrompt(); prompt.bind(capture); prompt.resize(420,230); prompt.show()
assert not prompt.save_button.isEnabled()
assert 'synthetic-pass' not in prompt.label.text()
assert 'https://fixture.invalid' in prompt.label.text()
prompt.success.setChecked(True)
assert prompt.save_button.isEnabled()
prompt.grab().save(str(root/'save-prompt.png'))
prompt.save_button.click()
key=vault.entries()[0].key
assert vault._for_fill(key,'https://fixture.invalid',authorized=True).password=='synthetic-pass'
assert capture.pending is None
click(); until(lambda: capture.pending is not None)
prompt.bind(capture); prompt.later.click(); assert capture.pending is None
click(); until(lambda: capture.pending is not None)
capture.expiry.timeout.emit(); assert capture.pending is None
click(); until(lambda: capture.pending is not None)
page.setHtml('another site',QUrl('https://different.invalid/'))
until(lambda: capture.pending is None)
load(); click(); until(lambda: capture.pending is not None)
prompt.bind(capture)
assert '更新' in prompt.save_button.text()
prompt.never.click(); assert capture.pending is None
assert vault.prompt_policy('https://fixture.invalid')=='never'
click(); assert capture.pending is None
vault.set_prompt('https://fixture.invalid','ask',confirmed=True)
click(); until(lambda: capture.pending is not None)
capture.discard()
# SPA shape observed on OA: no method/action; JS button, no native submit.
loaded.clear()
page.setHtml('<form><input id="u" value="spa-user"><input id="p" type="password" value="spa-secret">'
             '<button type="button" id="b" onclick="window.clicked=(window.clicked||0)+1">Login</button></form>',
             QUrl('https://fixture.invalid/login'))
until(lambda: loaded and loaded[-1]); until(lambda: capture.armed)
click(); until(lambda: capture.pending is not None)
assert capture.username=='spa-user'
assert js('window.clicked')==1, 'Capture replayed the website click'
from asset_based_agent.technical_platform.browser_login_scripts import probe_script, fill_script
assert json.loads(js(probe_script('spa'),1))['ok'], 'SPA cannot be filled'
assert json.loads(js(fill_script('spa','https://fixture.invalid','saved-user','saved-pass'),1))['ok']
assert js('window.clicked')==1, 'Fill submitted the SPA login'
assert js("(()=>{const e=new Event('submit',{bubbles:true,cancelable:true});document.querySelector('form').dispatchEvent(e);return e.defaultPrevented})()"), 'SPA fell back to native GET'
capture.discard()
js("document.querySelector('form').setAttribute('method','get')")
click(); assert capture.pending is None
assert not json.loads(js(probe_script('get'),1))['ok']
js("document.querySelector('form').removeAttribute('method')")
js("document.querySelector('form').setAttribute('action','https://other.invalid/login')")
click(); assert capture.pending is None
assert not json.loads(js(probe_script('cross'),1))['ok']
js("document.querySelector('form').removeAttribute('action')")
click(); until(lambda: capture.pending is not None)
capture.close(); assert capture.pending is None and not capture.armed
click(); assert capture.pending is None
import shiboken6
prompt.close(); shiboken6.delete(view); shiboken6.delete(page); shiboken6.delete(profile)
print('login-capture: ok')
'''
    result = subprocess.run([sys.executable, '-X', 'utf8', '-c', code, str(tmp_path)],
                            env=os.environ.copy(), capture_output=True, text=True,
                            timeout=60, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'login-capture: ok' in result.stdout
    assert 'synthetic-pass' not in result.stdout + result.stderr
