import os
import subprocess
import sys


def test_real_observation_excludes_secrets_and_hidden_content(tmp_path):
    code = r'''
import json,sys,time
from pathlib import Path
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QUrl
from PySide6.QtTest import QTest
from PySide6.QtWebEngineCore import QWebEnginePage,QWebEngineProfile
from asset_based_agent.technical_platform.browser_observation import observation_script
app=QApplication([]); root=Path(sys.argv[1]); profile=QWebEngineProfile('observation')
profile.setPersistentStoragePath(str(root/'profile')); profile.setCachePath(str(root/'cache'))
page=QWebEnginePage(profile); loaded=[]; page.loadFinished.connect(loaded.append)
from PySide6.QtWebEngineWidgets import QWebEngineView
view=QWebEngineView(page); view.resize(900,700); view.show()
page.setHtml('<h1>Project</h1><p>Visible report</p><button>Upload</button>'
    '<div style="display:none"><p>hidden-marker</p></div>'
    '<input value="secret-account"><input type="password" value="secret-password">'
    '<textarea>textarea-secret</textarea><div contenteditable="true">editable-secret</div>'
    '<p>secret-password</p><script>window.credential="script-secret"</script>'
    '<iframe srcdoc="iframe-secret"></iframe>',QUrl('https://fixture.invalid/?token=url-secret'))
def until(fn):
    end=time.monotonic()+10
    while not fn() and time.monotonic()<end: QTest.qWait(10)
    assert fn()
until(lambda: bool(loaded))
def js(script,world=1):
    out=[]; page.runJavaScript(script,world,out.append); until(lambda:bool(out)); return out[0]
raw=js(observation_script('nonce'))
result=json.loads(raw)
assert result['nonce']=='nonce' and result['origin']=='https://fixture.invalid'
assert 'Visible report' in result['text']
assert any(c['text']=='Upload' for c in result['controls'])
for secret in ('hidden-marker','secret-account','secret-password','textarea-secret','editable-secret','script-secret','iframe-secret','url-secret'):
    assert secret not in raw, secret
assert js('typeof globalThis.__zqObservation',0)=='undefined'
from asset_based_agent.technical_platform.browser_observation import click_script
js("window.clickCount=0; document.querySelector('button').addEventListener('click',()=>window.clickCount++)",0)
snapshot=json.loads(js(observation_script('click-one')))
target=next(c['id'] for c in snapshot['controls'] if c['text']=='Upload')
assert json.loads(js(click_script('click-one','https://fixture.invalid',target)))=={'status':'dispatched'}
assert js('window.clickCount',0)==1
assert json.loads(js(click_script('click-one','https://fixture.invalid',target)))=={'status':'rejected'}
snapshot=json.loads(js(observation_script('changed')))
js("document.querySelector('button').textContent='Delete'",0)
assert json.loads(js(click_script('changed','https://fixture.invalid',target)))=={'status':'rejected'}
assert js('window.clickCount',0)==1
js("document.querySelector('button').textContent='Upload'",0)
js(observation_script('value-changed'))
js("document.querySelector('input').value='changed-value'",0)
assert json.loads(js(click_script('value-changed','https://fixture.invalid',target)))=={'status':'rejected'}
assert js('window.clickCount',0)==1
js("document.querySelector('input').value='secret-account'",0)
from types import SimpleNamespace
from threading import Event
from asset_based_agent.technical_platform.browser_observer import BrowserObserver
from asset_based_agent.technical_platform.browser_task_leases import BrowserTaskLeases
from asset_based_agent.technical_platform.task_manager import TaskManager,TaskBinding
session=SimpleNamespace(owner='alice',owns_page=lambda p:p is page)
manager=TaskManager(); binding=TaskBinding('alice','p','s','t')
worker=SimpleNamespace(cancel=Event(),isRunning=lambda:True); manager.register(binding,worker)
leases=BrowserTaskLeases(session,manager); leases.register(page)
lease=leases.acquire(page,binding,worker,confirmed=True)
observer=BrowserObserver(leases,page,can_observe=lambda lease,origin:origin=='https://fixture.invalid',
                         can_click=lambda lease,observation,control:control.text=='Upload')
observed=[]; observer.observe(lease,observed.append); until(lambda:bool(observed))
assert observed[0].untrusted is True and 'Visible report' in observed[0].text
assert 'secret-password' not in observed[0].model_dump_json()
clicked=[]; target=next(c.id for c in observed[0].controls if c.text=='Upload')
observer.click(lease,observed[0],target,callback=clicked.append); until(lambda:bool(clicked))
assert clicked==['dispatched'] and js('window.clickCount',0)==2
leases.takeover(page)
observed=[]; observer.observe(lease,observed.append)
assert observed==[None]
observer.close(); leases.close()
from asset_based_agent.technical_platform.browser_observation import action_script
js("document.body.style.height='4000px';window.scrollTo(0,0)",0)
js(observation_script('scroll-one'))
assert json.loads(js(action_script('scroll-one','https://fixture.invalid','1','scroll','down')))=={'status':'dispatched'}
until(lambda:js('window.scrollY',0)>0)
assert js('window.scrollY',0)<=1000
assert json.loads(js(action_script('scroll-one','https://fixture.invalid','1','scroll','down')))=={'status':'rejected'}
js(observation_script('scroll-up'))
assert json.loads(js(action_script('scroll-up','https://fixture.invalid','1','scroll','up')))=={'status':'dispatched'}
until(lambda:js('window.scrollY',0)==0)
js("document.body.insertAdjacentHTML('afterbegin','<a id=download href=/report.xlsx download>Download report</a>')",0)
snapshot=json.loads(js(observation_script('download-one')))
target=next(c['id'] for c in snapshot['controls'] if c['text']=='Download report')
assert json.loads(js(action_script('download-one','https://fixture.invalid',target,'download','')))=={
    'status':'resolved','url':'https://fixture.invalid/report.xlsx'}
assert js('window.clickCount',0)==2, 'Resolving must not click or submit anything'
assert json.loads(js(action_script('download-one','https://fixture.invalid',target,'download','')))=={'status':'rejected'}
js("document.getElementById('download').href='https://other.invalid/report.xlsx'",0)
js(observation_script('download-outside'))
assert json.loads(js(action_script('download-outside','https://fixture.invalid',target,'download','')))=={'status':'rejected'}
js("document.body.appendChild(document.createTextNode('X'.repeat(30000)))",0)
limited=json.loads(js(observation_script('next')))
assert limited['truncated'] is True and len(limited['text'])<=12000
import shiboken6
shiboken6.delete(view); shiboken6.delete(page); shiboken6.delete(profile)
print('observation: ok')
'''
    result = subprocess.run([sys.executable, '-X', 'utf8', '-c', code, str(tmp_path)],
                            env=os.environ.copy(), capture_output=True, text=True, timeout=45, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'observation: ok' in result.stdout
