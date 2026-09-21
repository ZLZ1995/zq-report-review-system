"""Real WebEngine lifecycle is isolated from the desktop regression process."""
import os
import subprocess
import sys


def test_account_profile_storage_and_lifecycle(tmp_path):
    code = r'''
import sqlite3
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import shiboken6
from PySide6.QtCore import QEventLoop, QTimer, QUrl
from PySide6.QtWebEngineCore import QWebEngineSettings
from PySide6.QtWidgets import QApplication
from asset_based_agent.technical_platform.storage_preferences import StoragePreferences
from asset_based_agent.technical_platform.browser_profile import BrowserSession

root = Path(sys.argv[1])
program, data, target = root/'program', root/'data', root/'target'
for path in (program, data, target): path.mkdir()
settings = StoragePreferences(root/'index.sqlite', program)
settings.select('alice', data)
settings.select('bob', data)
app = QApplication([])
class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/redirect':
            self.send_response(302)
            self.send_header('Location', 'file:///D:/private-test.txt')
            self.end_headers()
            return
        body = b'<html><body>isolated browser profile</body></html>'
        self.send_response(200)
        self.send_header('Content-Type', 'text/html')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)
    def log_message(self, *args): pass
server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
threading.Thread(target=server.serve_forever, daemon=True).start()
with BrowserSession(settings, 'alice', environment='test') as first:
    profile = first.profile
    path = Path(profile.persistentStoragePath())
    assert path.is_relative_to(data)
    assert Path(profile.cachePath()).is_relative_to(data)
    assert Path(profile.downloadPath()).is_relative_to(data)
    assert not profile.isOffTheRecord()
    page = first.new_page()
    assert page.profile() == profile
    assert not profile.settings().testAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls)
    loop = QEventLoop()
    received = []
    def loaded(ok):
        if not ok:
            loop.quit()
            return
        page.toPlainText(lambda text: (received.append(text), loop.quit()))
    page.loadFinished.connect(loaded)
    timeout = QTimer()
    timeout.setSingleShot(True)
    timeout.timeout.connect(loop.quit)
    timeout.start(15000)
    page.load(QUrl(f'http://127.0.0.1:{server.server_port}/'))
    loop.exec()
    timeout.stop()
    assert received == ['isolated browser profile']
    page.loadFinished.disconnect(loaded)
    blocked = []
    page.blocked.connect(blocked.append)
    assert not page.acceptNavigationRequest(QUrl('file:///D:/private-test.txt'), page.NavigationType.NavigationTypeOther, True)
    assert not page.acceptNavigationRequest(QUrl('https://user:secret@example.com'), page.NavigationType.NavigationTypeOther, False)
    assert all('secret' not in message and 'private' not in message for message in blocked)
    assert page.chooseFiles(page.FileSelectionMode.FileSelectOpen, [], []) == []
    results = []
    page.loadFinished.connect(lambda ok: (results.append(ok), loop.quit()))
    timeout.start(15000)
    page.load(QUrl(f'http://127.0.0.1:{server.server_port}/redirect'))
    loop.exec()
    timeout.stop()
    assert results == [False], results
    assert page.url().scheme() != 'file'
    lock_probe = subprocess.run([sys.executable, '-c',
        'import sys; from PySide6.QtCore import QLockFile; lock=QLockFile(sys.argv[1]); '
        'lock.setStaleLockTime(0); sys.exit(1 if lock.tryLock(0) else 0)',
        str(path/'profile.lock')], timeout=10, check=False)
    assert lock_probe.returncode == 0
    try:
        with BrowserSession(settings, 'alice', environment='test'): pass
    except RuntimeError: pass
    else: raise AssertionError('Profile opened twice')
    try:
        settings.migrate('alice', target, confirmed=True, consumers_closed=True)
    except sqlite3.OperationalError: pass
    else: raise AssertionError('Live profile migrated')
    with BrowserSession(settings, 'bob', environment='test') as second:
        assert second.profile.persistentStoragePath() != str(path)
    with BrowserSession(settings, 'alice', environment='production') as production:
        assert Path(production.profile.persistentStoragePath()) != path
assert not shiboken6.isValid(page)
assert shiboken6.isValid(profile)
with BrowserSession(settings, 'alice', environment='test') as reopened:
    assert reopened.profile is profile
    assert Path(reopened.profile.persistentStoragePath()) == path
try:
    settings.migrate('alice', target, confirmed=True, consumers_closed=True)
except sqlite3.OperationalError: pass
else: raise AssertionError('Profile storage migrated before process exit')
try:
    with BrowserSession(settings, 'unknown', environment='test'): pass
except ValueError: pass
else: raise AssertionError('Unknown owner acquired profile')
print('profile-lifecycle: ok')
server.shutdown()
server.server_close()
'''
    environment = os.environ.copy()
    result = subprocess.run([sys.executable, '-X', 'utf8', '-c', code, str(tmp_path)],
                            env=environment, capture_output=True, text=True, timeout=60, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'profile-lifecycle: ok' in result.stdout
    from asset_based_agent.technical_platform.storage_preferences import (
        StoragePreferences,
    )
    settings = StoragePreferences(tmp_path/'index.sqlite', tmp_path/'program')
    settings.migrate('alice', tmp_path/'target', confirmed=True, consumers_closed=True)
    assert settings.load('alice').data_root == (tmp_path/'target').resolve()
