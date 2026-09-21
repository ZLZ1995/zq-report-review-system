import os
import subprocess
import sys


def test_real_form_fill_select_and_sensitive_field_exclusion(tmp_path):
    code = r'''
import json,sys,time
from pathlib import Path
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QUrl
from PySide6.QtTest import QTest
from PySide6.QtWebEngineCore import QWebEnginePage,QWebEngineProfile
from PySide6.QtWebEngineWidgets import QWebEngineView
from asset_based_agent.technical_platform.browser_observation import observation_script,action_script
app=QApplication([]); root=Path(sys.argv[1]); profile=QWebEngineProfile('form-actions')
profile.setPersistentStoragePath(str(root/'profile')); profile.setCachePath(str(root/'cache'))
page=QWebEnginePage(profile); view=QWebEngineView(page); view.resize(900,700); view.show()
loaded=[]; page.loadFinished.connect(loaded.append)
page.setHtml('<form method="post"><label for="project">Project name</label><input id="project">'
 '<label for="kind">Category</label><select id="kind"><option value="internal-a">Alpha</option><option value="internal-b">Beta</option></select>'
 '<input aria-label="Password" type="password"><input aria-label="Token" name="api_token">'
 '<input aria-label="Login" autocomplete="username"><input aria-label="Code" autocomplete="one-time-code">'
 '<label for="opaque">Password entry</label><input id="opaque" type="text">'
 '<button>Submit</button></form>',QUrl('https://fixture.invalid/'))
def until(fn):
    end=time.monotonic()+10
    while not fn() and time.monotonic()<end: QTest.qWait(10)
    assert fn()
until(lambda:bool(loaded))
def js(script,world=1):
    out=[]; page.runJavaScript(script,world,out.append); until(lambda:bool(out)); return out[0]
js("window.submits=0; document.querySelector('form').addEventListener('submit',e=>{e.preventDefault();window.submits++})",0)
snapshot=json.loads(js(observation_script('fill')))
labels=[c['text'] for c in snapshot['controls']]
assert 'Project name' in labels and 'Category' in labels
assert all(label not in labels for label in ('Password','Token','Login','Code','Password entry'))
target=next(c['id'] for c in snapshot['controls'] if c['text']=='Project name')
assert json.loads(js(action_script('fill','https://fixture.invalid',target,'fill','Demo project')))=={'status':'dispatched'}
assert js("document.getElementById('project').value",0)=='Demo project'
js("document.getElementById('project').type='text'",0)
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
observer=BrowserObserver(leases,page,can_observe=lambda *_:True,
    can_edit=lambda lease,observation,control,operation,value:control.text=='Project name' and value=='Approved title')
observed=[]; observer.observe(lease,observed.append); until(lambda:bool(observed))
assert observed[0] is not None
target=next(c.id for c in observed[0].controls if c.text=='Project name')
edited=[]; observer.edit(lease,observed[0],target,'fill','Approved title',callback=edited.append)
until(lambda:bool(edited)); assert edited==['dispatched']
assert js("document.getElementById('project').value",0)=='Approved title'
assert js('window.submits',0)==0
observer.close(); leases.close()
js("document.getElementById('project').value='Demo project'",0)
snapshot=json.loads(js(observation_script('select')))
assert 'Demo project' not in json.dumps(snapshot)
target=next(c for c in snapshot['controls'] if c['text']=='Category')
assert target['options']==[{'id':'1','text':'Alpha'},{'id':'2','text':'Beta'}]
assert 'internal-a' not in json.dumps(snapshot) and 'internal-b' not in json.dumps(snapshot)
assert json.loads(js(action_script('select','https://fixture.invalid',target['id'],'select','2')))=={'status':'dispatched'}
assert js("document.getElementById('kind').value",0)=='internal-b'
assert js('window.submits',0)==0
snapshot=json.loads(js(observation_script('changed')))
target=next(c['id'] for c in snapshot['controls'] if c['text']=='Project name')
js("document.getElementById('project').type='password'",0)
assert json.loads(js(action_script('changed','https://fixture.invalid',target,'fill','do-not-fill')))=={'status':'rejected'}
assert js("document.getElementById('project').value",0)=='Demo project'
import shiboken6
shiboken6.delete(view); shiboken6.delete(page); shiboken6.delete(profile)
print('form-actions: ok')
'''
    result = subprocess.run([sys.executable, '-X', 'utf8', '-c', code, str(tmp_path)],
                            env=os.environ.copy(), capture_output=True, text=True, timeout=45, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'form-actions: ok' in result.stdout
