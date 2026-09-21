import os
import subprocess
import sys


def test_real_navigation_redirect_scope_and_manual_takeover(tmp_path):
    code = r'''
import sys,time,threading
from pathlib import Path
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from types import SimpleNamespace
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest
from asset_based_agent.technical_platform.browser_profile import BrowserSession
from asset_based_agent.technical_platform.browser_navigation import BrowserNavigation
from asset_based_agent.technical_platform.browser_task_leases import BrowserTaskLeases
from asset_based_agent.technical_platform.task_manager import TaskManager,TaskBinding
from asset_based_agent.technical_platform.storage_preferences import StoragePreferences
hits=[]
class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args): pass
    def do_GET(self):
        hits.append(self.path)
        if self.path=='/redirect':
            self.send_response(302); self.send_header('Location','/forbidden'); self.end_headers(); return
        self.send_response(200); self.send_header('Content-Type','text/html'); self.end_headers()
        self.wfile.write(b'<h1>Fixture</h1>')
server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
threading.Thread(target=server.serve_forever,daemon=True).start()
base='http://127.0.0.1:'+str(server.server_port)
root=Path(sys.argv[1]); (root/'program').mkdir(); (root/'data').mkdir()
prefs=StoragePreferences(root/'index.sqlite',root/'program'); prefs.select('alice',root/'data')
app=QApplication([]); session=BrowserSession(prefs,'alice',environment='test'); session.__enter__()
page=session.new_page(); manager=TaskManager(); binding=TaskBinding('alice','p','s','t')
worker=SimpleNamespace(cancel=threading.Event(),isRunning=lambda:True); manager.register(binding,worker)
leases=BrowserTaskLeases(session,manager); leases.register(page)
lease=leases.acquire(page,binding,worker,confirmed=True)
nav=BrowserNavigation(leases,page,lease,can_navigate=lambda lease,url:url in (base+'/ok',base+'/redirect'))
def until(fn):
    end=time.monotonic()+12
    while not fn() and time.monotonic()<end: QTest.qWait(10)
    assert fn(), 'Navigation callback timed out'
results=[]; nav.navigate(base+'/ok',results.append); until(lambda:bool(results))
assert results==['loaded']
results=[]; nav.navigate(base+'/forbidden',results.append)
assert results==['rejected'] and '/forbidden' not in hits
results=[]; nav.navigate(base+'/redirect',results.append); until(lambda:bool(results))
assert results==['rejected'] and '/forbidden' not in hits, (results,hits)
worker.cancel.set()
assert not leases.valid(lease)
leases.takeover(page)
results=[]; nav.navigate(base+'/ok',results.append)
assert results==['rejected']
from PySide6.QtCore import QUrl
loaded=[]; page.loadFinished.connect(loaded.append); page.setUrl(QUrl(base+'/forbidden'))
until(lambda:bool(loaded)); assert loaded[-1] and '/forbidden' in hits
nav.close(); leases.close(); session.close(); server.shutdown(); server.server_close()
print('navigation: ok')
'''
    result = subprocess.run([sys.executable, '-X', 'utf8', '-c', code, str(tmp_path)],
                            env=os.environ.copy(), capture_output=True, text=True, timeout=60, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'navigation: ok' in result.stdout
