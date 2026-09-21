import os
import subprocess
import sys


def test_real_page_user_click_opens_tab(tmp_path):
    code = r'''
import sys, threading, time
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from PySide6.QtCore import QPoint, Qt, QUrl
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from asset_based_agent.technical_platform.storage_preferences import StoragePreferences
from asset_based_agent.technical_platform.browser_profile import BrowserSession
from asset_based_agent.technical_platform.browser_panel import BrowserPanel
root = Path(sys.argv[1])
program, data = root/'program', root/'data'
program.mkdir(); data.mkdir()
prefs = StoragePreferences(root/'index.sqlite', program)
prefs.select('synthetic', data)
class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        body = (b'<a style="position:absolute;left:0;top:0;width:180px;height:80px" '
                b'href="/target" target="_blank">Open target</a>') if self.path == '/' else b'<p>target page</p>'
        self.send_response(200)
        self.send_header('Content-Type', 'text/html')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers(); self.wfile.write(body)
    def log_message(self, *args): pass
server = ThreadingHTTPServer(('127.0.0.1',0), Handler)
threading.Thread(target=server.serve_forever, daemon=True).start()
app = QApplication([])
def until(predicate):
    end = time.monotonic()+15
    while not predicate() and time.monotonic()<end: QTest.qWait(20)
    assert predicate(), 'Timed out waiting for browser condition'
with BrowserSession(prefs, 'synthetic', environment='test') as session:
    panel = BrowserPanel(session)
    panel.resize(800,600); panel.show()
    source = panel.current_view()
    loaded = []
    source.loadFinished.connect(loaded.append)
    source.load(QUrl(f'http://127.0.0.1:{server.server_port}/'))
    until(lambda: loaded and loaded[-1] and source.url().path()=='/')
    seen = []
    source.page().newWindowRequested.connect(lambda request: seen.append(request.isUserInitiated()))
    QTest.mouseClick(source.focusProxy() or source, Qt.MouseButton.LeftButton, pos=QPoint(20,20))
    until(lambda: panel.tabs.count()==2 and panel.current_view().url().path()=='/target')
    assert seen == [True], seen
    assert panel.current_view().page().profile() is source.page().profile()
    panel.shutdown(); panel.close()
server.shutdown(); server.server_close()
print('real-popup: ok')
'''
    result = subprocess.run([sys.executable, '-X', 'utf8', '-c', code, str(tmp_path)],
                            env=os.environ.copy(), capture_output=True, text=True,
                            timeout=60, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'real-popup: ok' in result.stdout
