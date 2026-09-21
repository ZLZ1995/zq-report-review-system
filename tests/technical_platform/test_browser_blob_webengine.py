import os
import subprocess
import sys

import pytest


@pytest.mark.parametrize('handler', ['inline', 'listener'])
@pytest.mark.parametrize('trigger', ['isolated', 'mouse'])
def test_real_generated_download_from_https_document(tmp_path, handler, trigger):
    code = r'''
import sys, time, json
from pathlib import Path
from types import SimpleNamespace
from PySide6.QtCore import QPoint, Qt, QUrl
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile
from PySide6.QtWebEngineWidgets import QWebEngineView
from asset_based_agent.technical_platform.browser_download_controller import BrowserDownloads
from asset_based_agent.technical_platform.browser_observation import observation_script, action_script
import shiboken6
root=Path(sys.argv[1])
app=QApplication([])
def until(predicate):
    deadline=time.monotonic()+15
    while not predicate() and time.monotonic()<deadline: QTest.qWait(20)
    assert predicate(), 'generated download timeout'
profile=QWebEngineProfile('synthetic-blob')
profile.setPersistentStoragePath(str(root/'profile')); profile.setCachePath(str(root/'cache'))
class DiagnosticPage(QWebEnginePage):
    def javaScriptConsoleMessage(self,level,message,line,source):
        print('page-console',message,line,flush=True)
page=DiagnosticPage(profile); panel=QWebEngineView(); panel.setPage(page)
panel.resize(700,500); panel.show()
session=SimpleNamespace(profile=profile, owns_page=lambda value:value is page,
    download_journal=SimpleNamespace(track=lambda _:None, forget=lambda _:None))
controller=BrowserDownloads(session,lambda _:root/'generated.txt')
try:
    loaded=[]
    page.loadFinished.connect(loaded.append)
    html="""<html><body><button type="button" onclick="const a=document.createElement('a');
        a.href=window.URL.createObjectURL(new Blob(['synthetic-generated-content'],{type:'text/plain'}));
        a.download='generated.txt';document.body.appendChild(a);a.click();">Download</button></body></html>"""
    page.setHtml(html,QUrl('https://example.com/project/1'))
    until(lambda: loaded and loaded[-1] and not page.isLoading())
    handler_state=[]
    page.runJavaScript("JSON.stringify({handler:typeof document.querySelector('button').onclick,ready:document.readyState})",0,handler_state.append)
    until(lambda: handler_state)
    print('handler-state',handler_state,flush=True)
    if sys.argv[2]=='listener':
        registered=[]
        page.runJavaScript("""(()=>{const node=document.querySelector('button');node.removeAttribute('onclick');
            node.addEventListener('click',()=>{const a=document.createElement('a');
            a.href=window.URL.createObjectURL(new Blob(['synthetic-generated-content'],{type:'text/plain'}));
            a.download='generated.txt';document.body.appendChild(a);a.click();});return true;})();""",0,registered.append)
        until(lambda: registered)
    target=root/'generated.txt'; selected=[]; rejected=[]
    controller.choose=lambda name: selected.append(name) or target
    controller.rejected.connect(rejected.append)
    observed=[]; page.runJavaScript(observation_script('blob-test'),1,observed.append)
    until(lambda: observed)
    snapshot=json.loads(observed[0]); target_id=snapshot['controls'][0]['id']
    dispatched=[]
    if sys.argv[3]=='mouse':
        QTest.mouseClick(panel.focusProxy(), Qt.MouseButton.LeftButton, pos=QPoint(40,18))
    else:
        page.runJavaScript(action_script('blob-test','https://example.com',target_id,'download_button',''),
                           1,dispatched.append)
        until(lambda: dispatched)
        assert json.loads(dispatched[0])=={'status':'dispatched'}, (dispatched,snapshot)
    diagnostic=[]
    page.runJavaScript("JSON.stringify({links:document.querySelectorAll('a').length,html:document.body.innerHTML})",0,diagnostic.append)
    until(lambda: diagnostic)
    print('diagnostic',diagnostic,flush=True)
    until(lambda: rejected or (controller.records and all(r.status!='running' for r in controller.records.values())))
    assert not rejected, rejected
    assert selected==['generated.txt'], selected
    assert target.read_bytes()==b'synthetic-generated-content'
    assert all(r.status=='completed' for r in controller.records.values())
finally:
    controller.close(); panel.close(); shiboken6.delete(panel)
    shiboken6.delete(page); shiboken6.delete(profile)
print('generated-download-ok')
'''
    result = subprocess.run([sys.executable, '-X', 'utf8', '-c', code, str(tmp_path), handler, trigger],
                            env=dict(os.environ, QT_QPA_PLATFORM='offscreen'),
                            capture_output=True, text=True, encoding='utf-8', timeout=40, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'generated-download-ok' in result.stdout
