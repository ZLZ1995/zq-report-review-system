import os
import subprocess
import sys


def test_real_http_download_confirm_complete_and_decline(tmp_path):
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
from asset_based_agent.technical_platform import browser_download_view as dv
root = Path(sys.argv[1])
program, data = root/'program', root/'data'
program.mkdir(); data.mkdir()
prefs = StoragePreferences(root/'index.sqlite', program)
prefs.select('synthetic', data)
payload = b'synthetic download\n'*8192
trace = {'requests': [], 'rejected': [], 'states': [], 'loaded': []}
class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        trace['requests'].append(self.path)
        if self.path=='/index':
            self.send_response(200)
            self.send_header('Content-Type','text/html; charset=utf-8')
            self.end_headers()
            self.wfile.write(b'<style>body{margin:0}a{display:block;width:240px;height:40px;margin:20px}</style>'
                             b'<a href="/one">Download one</a><a href="/two">Download two</a>'
                             b'<a href="/slow">Slow download</a>')
            return
        self.send_response(200)
        self.send_header('Content-Type', 'application/octet-stream')
        self.send_header('Content-Disposition', 'attachment; filename="sample.txt"')
        self.send_header('Content-Length', str(len(payload)))
        self.end_headers()
        try:
            if self.path == '/slow':
                for index in range(0, len(payload), 4096):
                    self.wfile.write(payload[index:index+4096]); self.wfile.flush()
                    time.sleep(0.03)
            else: self.wfile.write(payload)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError): pass
    def log_message(self, *args): pass
server = ThreadingHTTPServer(('127.0.0.1',0), Handler)
threading.Thread(target=server.serve_forever, daemon=True).start()
app = QApplication([])
def until(predicate):
    end = time.monotonic()+20
    while not predicate() and time.monotonic()<end: QTest.qWait(20)
    assert predicate(), f'Download condition timed out: {trace}; selections={selected}; records={controller.records}'
with BrowserSession(prefs, 'synthetic', environment='test') as session:
    panel = BrowserPanel(session)
    panel.resize(800,600); panel.show()
    page = panel.current_view().page()
    page.loadFinished.connect(trace['loaded'].append)
    destination = root/'download.txt'
    selected = []
    def choose(*args, **kwargs):
        selected.append(Path(args[2]).name)
        assert Path(args[2]).is_relative_to(data)
        if len(selected)==1: return str(destination), ''
        if len(selected)==3: return str(root/'cancelled.txt'), ''
        return '', ''
    dv.QFileDialog.getSaveFileName = choose
    controller = panel.downloads.controller
    controller.rejected.connect(trace['rejected'].append)
    session.profile.downloadRequested.connect(lambda item: trace['states'].append({
        'state':str(item.state()), 'has_page':item.page() is not None,
        'owned_page':session.owns_page(item.page()), 'save_page':item.isSavePageDownload(),
        'controller_closed':controller._closed,
    }))
    events = []
    controller.changed.connect(events.append)
    # Trigger via actual page content. Direct page.download during initial
    # about:blank setup can have no originating page; rejecting it is correct.
    page.setUrl(QUrl(f'http://127.0.0.1:{server.server_port}/index'))
    until(lambda: trace['loaded'] and trace['loaded'][-1] and not page.isLoading()
          and page.url().path()=='/index')
    QTest.mouseClick(panel.current_view().focusProxy(), Qt.MouseButton.LeftButton, pos=QPoint(50,40))
    until(lambda: controller.records and all(r.status!='running' for r in controller.records.values()))
    assert selected == ['sample.txt'], selected
    record = next(iter(controller.records.values()))
    assert record.status == 'completed', record
    assert record.received == len(payload) and record.total == len(payload), record
    assert destination.read_bytes() == payload
    assert not record.target.stage.exists()
    row = panel.downloads.rows[next(iter(controller.records))]
    assert '已完成' in row.status.text() and not row.cancel.isEnabled()
    assert row.progress.value()==100
    QTest.mouseClick(panel.current_view().focusProxy(), Qt.MouseButton.LeftButton, pos=QPoint(50,100))
    until(lambda: len(selected)==2)
    QTest.qWait(100)
    assert len(controller.records)==1
    assert destination.read_bytes()==payload
    assert events
    QTest.mouseClick(panel.current_view().focusProxy(), Qt.MouseButton.LeftButton, pos=QPoint(50,160))
    until(lambda: len(controller.records)==2 and any(r.status=='running' for r in controller.records.values()))
    running_key = next(key for key, r in controller.records.items() if r.status=='running')
    panel.downloads.hide()
    until(lambda: controller.records[running_key].received > 0)
    assert controller.records[running_key].status == 'running'
    assert not panel.downloads.isVisible(), 'Progress must not reopen a hidden list'
    panel.downloads.show()
    panel.downloads.rows[running_key].cancel.click()
    until(lambda: all(r.status!='running' for r in controller.records.values()))
    cancelled = [r for r in controller.records.values() if r.status=='cancelled']
    assert len(cancelled)==1, controller.records
    assert not (root/'cancelled.txt').exists()
    QTest.qWait(200)
    assert cancelled[0].cleanup_pending, cancelled[0]
    assert not (root/'cancelled.txt').exists()
    assert session.download_journal is not None
    assert '已取消' in panel.downloads.rows[running_key].status.text()
    assert not panel.downloads.rows[running_key].cancel.isEnabled()
    panel.downloads.show()
    QTest.qWait(30)
    panel.downloads.grab().save(str(root/'downloads.png'))
    panel.shutdown(); panel.close()
with BrowserSession(prefs, 'synthetic', environment='test') as reopened:
    assert list(root.glob('.zq-download-*')), 'Same-process reuse must not reclaim staging'
server.shutdown(); server.server_close()
print('real-download: ok')
'''
    result = subprocess.run([sys.executable, '-X', 'utf8', '-c', code, str(tmp_path)],
                            env=os.environ.copy(), capture_output=True, text=True,
                            timeout=60, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'real-download: ok' in result.stdout
    recovery = r'''
import sys
from pathlib import Path
from PySide6.QtWidgets import QApplication
from asset_based_agent.technical_platform.storage_preferences import StoragePreferences
from asset_based_agent.technical_platform.browser_profile import BrowserSession
root = Path(sys.argv[1])
assert list(root.glob('.zq-download-*')), 'Expected retained cancelled staging'
app = QApplication([])
prefs = StoragePreferences(root/'index.sqlite', root/'program')
with BrowserSession(prefs, 'synthetic', environment='test') as session:
    assert not list(root.glob('.zq-download-*')), 'Cold recovery did not clear registered staging'
    assert (root/'download.txt').read_bytes() == b'synthetic download\n'*8192
    assert not (root/'cancelled.txt').exists()
print('download-recovery: ok')
'''
    recovered = subprocess.run([sys.executable, '-X', 'utf8', '-c', recovery, str(tmp_path)],
                               env=os.environ.copy(), capture_output=True, text=True,
                               timeout=40, check=False)
    assert recovered.returncode == 0, recovered.stdout + recovered.stderr
    assert 'download-recovery: ok' in recovered.stdout
