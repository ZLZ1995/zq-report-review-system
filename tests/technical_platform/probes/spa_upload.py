"""Reproduce the observed visible upload component without contacting OA."""
import json
import os
import sys
import time
from hashlib import sha256
from pathlib import Path

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'src'))
from PySide6.QtCore import QUrl
from PySide6.QtTest import QTest
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QApplication

from asset_based_agent.technical_platform.browser_observation import observation_script
from asset_based_agent.technical_platform.browser_upload_script import upload_script

app = QApplication([])
root = Path(sys.argv[1]); case = sys.argv[2]
root.mkdir(parents=True, exist_ok=True)
profile = QWebEngineProfile('spa-probe')
profile.setPersistentStoragePath(str(root / 'profile')); profile.setCachePath(str(root / 'cache'))
page = QWebEnginePage(profile); view = QWebEngineView(page); view.resize(900, 600); view.show()
loaded = []
page.loadFinished.connect(loaded.append)
markup = '<form><div role="button"><button type="button">Upload synthetic report</button><input type="file" style="display:none"></div></form>'
if case == 'hidden_wrapper': markup = markup.replace('<div ', '<div hidden ')
if case == 'ambiguous': markup = markup.replace('</div>', '<input type="file" style="display:none"></div>')
if case == 'disabled': markup = markup.replace('<button ', '<button disabled ')
if case == 'cross_origin': markup = markup.replace('<form>', '<form method="post" action="https://other.invalid/upload">')
if case == 'explicit_get': markup = markup.replace('<form>', '<form method="get" action="/upload">')
if case == 'submit_button': markup = markup.replace('type="button"', 'type="submit"')
markup += '<script>window.changed=0;document.querySelector("input").addEventListener("change",async e=>{window.changed++;window.body=await e.target.files[0].text();});</script>'
page.setHtml(markup, QUrl('https://example.com/project/20'))
def until(check):
    end = time.monotonic() + 10
    while not check() and time.monotonic() < end: QTest.qWait(10)
    assert check()
def js(script, world=1):
    results = []; page.runJavaScript(script, world, results.append)
    until(lambda: bool(results)); return results[0]
try:
    until(lambda: bool(loaded))
    assert not any(c['kind'] == 'file' for c in json.loads(js(observation_script('no-permission')))['controls'])
    observed = json.loads(js(observation_script('allowed', include_files=True)))
    files = [c for c in observed['controls'] if c['kind'] == 'file']
    if case in {'hidden_wrapper', 'ambiguous', 'submit_button'}:
        assert files == [], files
        print('spa-upload-component: passed'); sys.exit(0)
    assert len(files) == 1, {'file_controls': files, 'root': str(root)}
    assert files[0]['text'] == 'Upload synthetic report'
    result = json.loads(js(upload_script('begin', 'probe', nonce='allowed', target=files[0]['id'],
        origin='https://example.com', name='synthetic.txt', size=3, sha256=sha256(b'syn').hexdigest())))
    if case in {'disabled', 'cross_origin', 'explicit_get'}:
        assert files[0]['disabled'] is True and result == {'status': 'rejected'}, result
    else:
        assert result == {'status': 'ready'}, result
        if case == 'mutated':
            js('document.querySelector("button").textContent="Different object"', 0)
        chunk = json.loads(js(upload_script('chunk', 'probe', data='c3lu')))
        if case == 'mutated':
            assert chunk == {'status': 'rejected'}
        else:
            assert chunk == {'status': 'ready'}
            js(upload_script('finish', 'probe'))
            until(lambda: json.loads(js(upload_script('status', 'probe')))['status'] != 'verifying')
            assert js('window.changed', 0) == 0
            assert json.loads(js(upload_script('commit', 'probe'))) == {'status': 'dispatched'}
            until(lambda: js('window.body', 0) == 'syn')
    assert js('window.changed', 0) == (1 if case == 'normal' else 0)
    print('spa-upload-component: passed')
finally:
    import shiboken6
    shiboken6.delete(view); shiboken6.delete(page); shiboken6.delete(profile)
