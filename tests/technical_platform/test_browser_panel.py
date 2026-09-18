import os
import subprocess
import sys


def test_window_browser_tabs_hide_and_close(tmp_path):
    code = r'''
import sys
from pathlib import Path
import shiboken6
from PySide6.QtWidgets import QApplication
from asset_based_agent.technical_platform.app import PlatformWindow
from asset_based_agent.technical_platform.store import PlatformStore
from asset_based_agent.technical_platform.storage_preferences import StoragePreferences
root = Path(sys.argv[1])
program, data = root/'program', root/'data'
program.mkdir(); data.mkdir()
prefs = StoragePreferences(root/'index.sqlite', program)
prefs.select('alice', data)
prefs.select('bob', data)
qt = QApplication([])
window = PlatformWindow(PlatformStore(root/'project.sqlite', 'alice'), storage_preferences=prefs)
window.show()
window.toggle_browser()
qt.processEvents()
panel = window.browser_panel
assert panel.tabs.count() == 1
assert panel.task_leases.manager is window.task_manager
from threading import Event
from types import SimpleNamespace
from PySide6.QtTest import QTest
from asset_based_agent.technical_platform.task_manager import TaskBinding
binding=TaskBinding('alice','test-project','test-session','test-task')
worker=SimpleNamespace(cancel=Event(),isRunning=lambda:True)
window.task_manager.register(binding,worker)
lease=panel.task_leases.acquire(panel.current_view().page(),binding,worker,confirmed=True)
assert panel.task_leases.valid(lease)
QTest.keyClicks(panel.address,'x')
assert not panel.task_leases.valid(lease), 'Native address typing did not take control'
lease=panel.task_leases.acquire(panel.current_view().page(),binding,worker,confirmed=True)
QTest.mouseClick(panel.current_view().focusProxy(), __import__('PySide6.QtCore',fromlist=['Qt']).Qt.MouseButton.LeftButton)
assert not panel.task_leases.valid(lease), 'Native page click did not take control'
second=panel.new_tab(blank=False)
second_binding=TaskBinding('alice','test-project','second-session','second-task')
second_worker=SimpleNamespace(cancel=Event(),isRunning=lambda:True)
window.task_manager.register(second_binding,second_worker)
background=panel.task_leases.acquire(panel.tabs.widget(0).page(),binding,worker,confirmed=True)
foreground=panel.task_leases.acquire(second.page(),second_binding,second_worker,confirmed=True)
QTest.keyClicks(panel.address,'y')
assert panel.task_leases.valid(background), 'User action affected unrelated tab'
assert not panel.task_leases.valid(foreground)
panel.close_tab(1)
assert panel.task_leases.valid(background)
window.toggle_browser(); window.toggle_browser()
assert panel.task_leases.valid(background), 'Hiding browser revoked task'
worker.cancel.set()
assert not panel.task_leases.valid(background)
second_worker.isRunning=lambda:False
window.task_manager.finish(second_binding,second_worker)
worker.isRunning=lambda:False
window.task_manager.finish(binding,worker)
assert panel.save_prompt.capture is panel.login_captures[panel.current_view()]
assert panel.save_prompt.isHidden()
from types import SimpleNamespace
cancelled=[]
panel.login_actions.active=(object(),SimpleNamespace(close=lambda: cancelled.append('tab')))
panel.new_tab(); panel.close_tab(1)
assert len(panel.login_captures)==1
assert panel.save_prompt.capture is panel.login_captures[panel.current_view()]
assert cancelled==['tab']
panel.login_actions.active=(object(),SimpleNamespace(close=lambda: cancelled.append('hide')))
window.toggle_browser(); window.toggle_browser()
assert cancelled==['tab','hide']
from asset_based_agent.technical_platform import browser_panel as bp
bp.QInputDialog.getText = lambda *args, **kwargs: ('我的主页', True)
panel.add_bookmark()
assert panel.library.bookmarks() == [('我的主页', 'about:blank')]
panel.address.setText('https://not-submitted.example/')
panel.refresh_bookmarks()
panel.refresh_bookmarks()
panel.bookmark_menu.actions()[-1].menu().actions()[0].trigger()
assert panel.address.text() == 'about:blank'
bp.QMessageBox.question = lambda *args, **kwargs: bp.QMessageBox.StandardButton.No
panel.library.set_home('https://example.com/')
panel.set_current_home()
assert panel.library.home() == 'https://example.com/'
bp.QMessageBox.question = lambda *args, **kwargs: bp.QMessageBox.StandardButton.Yes
panel.set_current_home()
assert panel.library.home() == 'about:blank'
panel.remove_bookmark('about:blank')
assert panel.library.bookmarks() == []
page = panel.current_view().page()
from PySide6.QtCore import QUrl
from PySide6.QtWebEngineCore import QWebEngineNewWindowRequest
class Popup:
    def __init__(self, address, user=True):
        self.address, self.user, self.target = address, user, None
    def requestedUrl(self): return QUrl(self.address)
    def isUserInitiated(self): return self.user
    def destination(self): return QWebEngineNewWindowRequest.DestinationType.InNewBackgroundTab
    def openIn(self, target): self.target = target
source = panel.current_view()
for address, user in [('https://example.com/', False), ('file:///D:/private.txt', True)]:
    popup = Popup(address, user)
    panel.open_popup(source, popup)
    assert popup.target is None and panel.tabs.count() == 1
popup = Popup('https://example.com/')
panel.open_popup(source, popup)
assert panel.tabs.count() == 2 and popup.target is not None
assert popup.target.profile() is page.profile()
assert panel.current_view() is source
panel.close_tab(1)
while panel.tabs.count() < 12:
    panel.new_tab(blank=False)
limited = Popup('https://example.com/')
panel.open_popup(source, limited)
assert limited.target is None and panel.tabs.count() == 12
while panel.tabs.count() > 1:
    panel.close_tab(panel.tabs.count()-1)
assert page.url().isEmpty() or page.url().toString() == 'about:blank'
panel.new_tab()
assert panel.tabs.count() == 2
panel.close_tab(1)
assert panel.tabs.count() == 1
assert panel.current_view().page() is page
window.toggle_browser()
assert not window.details.isVisible()
window.toggle_browser()
assert window.details.isVisible() and panel.current_view().page() is page
panel.address.setText('file:///D:/private.txt')
panel.navigate()
assert '不安全' in panel.status.text()
panel.loading(panel.current_view(), True)
assert '不安全' in panel.status.text(), 'Late load completion erased validation error'
panel.current_view().setProperty('notice', None)
panel.current_view().setProperty('noticeKind', None)
panel.loading(panel.current_view(), None)
assert panel.status.text() == '正在加载网页…'
panel.loading(panel.current_view(), False)
assert panel.status.text() == '网页加载失败，请检查网络后重试。'
assert '安全策略' not in panel.status.text()
panel.loading(panel.current_view(), None)
panel.stop_loading()
assert panel.status.text() == '已停止加载。'
panel.loading(panel.current_view(), False)
assert panel.status.text() == '已停止加载。'
panel.loading(panel.current_view(), None)
panel.loading_timed_out(panel.current_view())
assert '长时间未完成加载' in panel.status.text()
assert panel.retry_button.isVisibleTo(panel)
assert panel.external_button.isVisibleTo(panel)
panel.loading(panel.current_view(), True)
assert panel.status.text() == '加载完成'
assert not panel.retry_button.isVisibleTo(panel)
assert not panel.external_button.isVisibleTo(panel)
panel.security_blocked(panel.current_view(), '已阻止不安全的网页请求。')
panel.loading(panel.current_view(), False)
assert panel.status.text() == '已阻止不安全的网页请求。'
panel.address.setText('https://typed.example/')
panel.address.textEdited.emit('https://typed.example/')
other = panel.new_tab()
panel.tabs.setCurrentIndex(0)
other.page().blocked.emit('background blocked')
other.urlChanged.emit(other.url())
assert panel.address.text() == 'https://typed.example/'
assert panel.status.text() != 'background blocked'
panel.close_tab(1)
assert not page.url().toString().startswith('file:')
window.resize(1440,900)
qt.processEvents()
assert panel.width() <= window.details.width(), (panel.width(), window.details.width())
window.grab().save(str(root/'browser-panel.png'))
from types import SimpleNamespace
from asset_based_agent.technical_platform import app as platform
platform.authenticate = lambda *args: (SimpleNamespace(), {
    'owner': 'bob', 'models': [], 'balance': {'balance': '100.00'}})
assert window.connect_service()
assert window.browser_panel is None
assert not shiboken6.isValid(page)
window.toggle_browser()
page = window.browser_panel.current_view().page()
assert window.browser_panel.session.owner == 'bob'
window.close()
qt.processEvents()
assert not shiboken6.isValid(page)
print('browser-panel: ok')
'''
    result = subprocess.run([sys.executable, '-X', 'utf8', '-c', code, str(tmp_path)],
                            env=os.environ.copy(), capture_output=True, text=True,
                            timeout=60, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'browser-panel: ok' in result.stdout
