import os
import subprocess
import sys

import pytest


def test_real_isolated_upload_script_bounds_and_dom_guards(tmp_path):
    code = r'''
import base64,json,sys,time
from hashlib import sha256
from pathlib import Path
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QUrl
from PySide6.QtTest import QTest
from PySide6.QtWebEngineCore import QWebEnginePage,QWebEngineProfile
from PySide6.QtWebEngineWidgets import QWebEngineView
from asset_based_agent.technical_platform.browser_observation import observation_script
from asset_based_agent.technical_platform.browser_upload_script import upload_script
app=QApplication([]); root=Path(sys.argv[1]); profile=QWebEngineProfile('upload-script')
profile.setPersistentStoragePath(str(root/'profile')); profile.setCachePath(str(root/'cache'))
page=QWebEnginePage(profile); view=QWebEngineView(page); view.resize(900,700); view.show()
loaded=[]; page.loadFinished.connect(loaded.append)
page.setHtml('<form method=post action=/upload><label for=f>Artifact</label><input type=file id=f></form>'
 '<script>window.changed=0;document.getElementById("f").addEventListener("change",async e=>{'
 'window.changed++;window.body=await e.target.files[0].text();});</script>',QUrl('https://fixture.invalid/'))
def until(fn):
 end=time.monotonic()+10
 while not fn() and time.monotonic()<end: QTest.qWait(10)
 assert fn()
def js(script,world=1):
 out=[]; page.runJavaScript(script,world,out.append); until(lambda:bool(out)); return out[0]
until(lambda:bool(loaded))
assert not any(c['kind']=='file' for c in json.loads(js(observation_script('old')))['controls'])
def start(token,expected=None):
 snap=json.loads(js(observation_script(token,include_files=True)))
 target=next(c['id'] for c in snap['controls'] if c['kind']=='file')
 return json.loads(js(upload_script('begin',token,origin='https://fixture.invalid',
   nonce=token,target=target,name='synthetic.txt',size=3,sha256=expected or sha256(b'syn').hexdigest())))
assert start('one')=={'status':'ready'}
for offset,part in enumerate((b's',b'y',b'n')):
 assert json.loads(js(upload_script('chunk','one',data=base64.b64encode(part).decode(),offset=offset)))=={'status':'ready'}
assert json.loads(js(upload_script('finish','one')))['status']=='verifying'
until(lambda:json.loads(js(upload_script('status','one')))['status']!='verifying')
assert json.loads(js(upload_script('status','one')))=={'status':'verified'}
assert js('window.changed',0)==0
assert json.loads(js(upload_script('commit','one')))=={'status':'dispatched'}
until(lambda:js('window.body',0)=='syn')
assert js('window.changed',0)==1
assert js('typeof globalThis.__zqUpload',0)=='undefined'
assert json.loads(js(upload_script('chunk','one',data='c3lu')))=={'status':'rejected'}
js('document.getElementById("f").value=""',0)
assert start('mutated')=={'status':'ready'}
js('document.querySelector("label").textContent="Other object"',0)
assert json.loads(js(upload_script('chunk','mutated',data='c3lu')))=={'status':'rejected'}
assert js('window.changed',0)==1
assert start('wrong-digest','0'*64)=={'status':'ready'}
js(upload_script('chunk','wrong-digest',data='c3lu')); js(upload_script('finish','wrong-digest'))
until(lambda:json.loads(js(upload_script('status','wrong-digest')))['status']!='verifying')
assert json.loads(js(upload_script('status','wrong-digest')))=={'status':'rejected'}
assert js('window.changed',0)==1
assert start('cancel')=={'status':'ready'}
assert json.loads(js(upload_script('abort','cancel')))=={'status':'rejected'}
assert json.loads(js(upload_script('chunk','cancel',data='c3lu')))=={'status':'rejected'}
assert start('cancel-after-verify')=={'status':'ready'}
js(upload_script('chunk','cancel-after-verify',data='c3lu'))
js(upload_script('finish','cancel-after-verify'))
until(lambda:json.loads(js(upload_script('status','cancel-after-verify')))['status']!='verifying')
assert json.loads(js(upload_script('status','cancel-after-verify')))=={'status':'verified'}
js(upload_script('abort','cancel-after-verify'))
assert json.loads(js(upload_script('commit','cancel-after-verify')))=={'status':'rejected'}
assert js('window.changed',0)==1
assert start('offset')=={'status':'ready'}
assert json.loads(js(upload_script('chunk','offset',data='c3lu',offset=1)))=={'status':'rejected'}
js('document.getElementById("f").disabled=true',0)
assert start('disabled')=={'status':'rejected'}
js('document.getElementById("f").disabled=false',0)
js('document.querySelector("form").action="https://other.invalid/upload"',0)
assert start('cross-origin')=={'status':'rejected'}
assert js('window.changed',0)==1
import shiboken6
shiboken6.delete(view); shiboken6.delete(page); shiboken6.delete(profile)
print('upload-script: ok')
'''
    result = subprocess.run([sys.executable, '-X', 'utf8', '-c', code, str(tmp_path)],
                            env=os.environ.copy(), capture_output=True, text=True, timeout=50, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'upload-script: ok' in result.stdout


@pytest.mark.parametrize('changes', [
    {'name': '../raw.docx'}, {'size': 64 * 1024 * 1024 + 1}, {'size': True},
    {'origin': 'http://example.com'}, {'sha256': 'bad'}, {'target': 'document.body'},
])
def test_upload_script_rejects_invalid_metadata(changes):
    from asset_based_agent.technical_platform.browser_upload_script import upload_script
    values = {'origin': 'https://example.com', 'nonce': 'n', 'target': '1',
              'name': 'test.docx', 'size': 3, 'sha256': 'a' * 64}
    values.update(changes)
    with pytest.raises(ValueError): upload_script('begin', 'native-token', **values)


def test_upload_script_rejects_unbounded_chunks_and_arbitrary_operations():
    from asset_based_agent.technical_platform.browser_upload_script import upload_script
    with pytest.raises(ValueError): upload_script('evaluate', 'native-token')
    with pytest.raises(ValueError): upload_script('chunk', 'native-token', data='X' * 90000)
    with pytest.raises(ValueError): upload_script('chunk', 'native-token', data='not base64')
