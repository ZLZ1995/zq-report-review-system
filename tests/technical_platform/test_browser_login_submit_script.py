import os
import subprocess
import sys


def test_login_submit_is_opt_in_single_use_and_revalidates_dom(tmp_path):
    code = r'''
import json,sys,time
from pathlib import Path
from PySide6.QtCore import QUrl
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest
from PySide6.QtWebEngineCore import QWebEnginePage,QWebEngineProfile
from asset_based_agent.technical_platform.browser_login_scripts import probe_script,fill_script,submit_script
app=QApplication([]); root=Path(sys.argv[1])
profile=QWebEngineProfile('submit-test'); profile.setPersistentStoragePath(str(root/'profile')); profile.setCachePath(str(root/'cache'))
page=QWebEnginePage(profile)
def until(f):
    end=time.monotonic()+8
    while not f() and time.monotonic()<end: QTest.qWait(10)
    assert f()
def js(code,world=1):
    results=[]; page.runJavaScript(code,world,results.append); until(lambda:bool(results)); return results[0]
for case in ('accept','default','changed_password','cross_origin','duplicate','extra_input_submit','invalid_form','expired'):
    loaded=[]; page.loadFinished.connect(loaded.append)
    page.setHtml('<form method="post" action="/login"><input id="u" autocomplete="username"><input id="p" type="password"><button>Login</button></form>',QUrl('https://fixture.invalid/'))
    until(lambda:bool(loaded)); page.loadFinished.disconnect(loaded.append)
    js("window.count=0;document.querySelector('form').addEventListener('submit',e=>{e.preventDefault();window.count++})",0)
    assert json.loads(js(probe_script('ticket')))['ok']
    args={} if case=='default' else {'prepare_submit':True}
    assert json.loads(js(fill_script('ticket','https://fixture.invalid','user','secret',**args)))=={'ok':True}
    assert js('window.count',0)==0
    if case=='changed_password': js("document.getElementById('p').value='edited'",0)
    if case=='cross_origin': js("document.querySelector('form').action='https://other.invalid/'",0)
    if case=='duplicate': js("document.querySelector('form').appendChild(document.createElement('button'))",0)
    if case=='extra_input_submit': js("const b=document.createElement('input');b.type='submit';document.querySelector('form').appendChild(b)",0)
    if case=='invalid_form': js("const b=document.createElement('input');b.required=true;document.querySelector('form').appendChild(b)",0)
    if case=='expired': js('globalThis.__zqLoginSubmit.deadline=0')
    result=json.loads(js(submit_script('ticket','https://fixture.invalid')))
    assert result=={'dispatched':case=='accept'},result
    assert js('window.count',0)==(1 if case=='accept' else 0)
    assert json.loads(js(submit_script('ticket','https://fixture.invalid')))=={'dispatched':False}
    assert js('typeof globalThis.__zqLoginSubmit',0)=='undefined'
import shiboken6
shiboken6.delete(page); shiboken6.delete(profile)
'''
    result = subprocess.run([sys.executable, '-X', 'utf8', '-c', code, str(tmp_path)],
        env=dict(os.environ, QT_QPA_PLATFORM='offscreen'), capture_output=True, text=True,
        encoding='utf-8', timeout=40, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
