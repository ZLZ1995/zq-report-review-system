"""Standalone, lazily opened browser panel; no site is privileged or preloaded."""
import sqlite3
from typing import cast

from PySide6.QtCore import QTimer, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWebEngineCore import QWebEngineNewWindowRequest
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import (
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
    QStyle,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .browser_download_view import DownloadsDialog
from .browser_library import BrowserLibrary
from .browser_login_actions import BrowserLoginActions
from .browser_login_capture import LoginCapture
from .browser_login_save_prompt import LoginSavePrompt
from .browser_policy import navigation_url
from .browser_takeover import BrowserTakeover
from .browser_task_leases import BrowserTaskLeases


class BrowserPanel(QWidget):
    LOAD_TIMEOUT_MS = 20_000

    def __init__(self, session, parent=None, *, task_manager=None):
        super().__init__(parent)
        self.session = session
        self.task_leases = BrowserTaskLeases(session, task_manager)
        self.credentials_dialog = None
        self.login_captures: dict[QWebEngineView, LoginCapture] = {}
        self.load_timers: dict[QWebEngineView, QTimer] = {}
        self.library = BrowserLibrary(session.preferences, session.owner, environment=session.environment)
        self.setMinimumWidth(360)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)
        toolbar = QHBoxLayout()
        toolbar.setSpacing(4)
        for title, icon, action in (
            ('后退', QStyle.StandardPixmap.SP_ArrowBack, lambda: self.current_view().back()),
            ('前进', QStyle.StandardPixmap.SP_ArrowForward, lambda: self.current_view().forward()),
            ('刷新', QStyle.StandardPixmap.SP_BrowserReload, lambda: self.current_view().reload()),
            ('停止加载', QStyle.StandardPixmap.SP_BrowserStop, self.stop_loading),
            ('主页', QStyle.StandardPixmap.SP_DirHomeIcon, self.open_home),
        ):
            button = QPushButton(self.style().standardIcon(icon), '', self)
            button.setToolTip(title)
            button.setAccessibleName(title)
            button.setFixedSize(32, 32)
            button.clicked.connect(action)
            toolbar.addWidget(button)
        new = QPushButton('新标签', self)
        new.clicked.connect(lambda: self.new_tab())
        toolbar.addStretch()
        toolbar.addWidget(new)
        bookmarks = QPushButton('书签', self)
        self.bookmark_menu = QMenu(bookmarks)
        self._bookmark_submenus = []
        self.bookmark_menu.aboutToShow.connect(self.refresh_bookmarks)
        bookmarks.setMenu(self.bookmark_menu)
        toolbar.addWidget(bookmarks)
        layout.addLayout(toolbar)
        self.address = QLineEdit(self)
        self.address.setPlaceholderText('输入网址，例如 https://example.com')
        self.address.setAccessibleName('网页地址')
        self.address.setMinimumHeight(34)
        self.address.returnPressed.connect(self.navigate)
        self.address.textEdited.connect(self.remember_address)
        layout.addWidget(self.address)
        self.save_prompt = LoginSavePrompt(self)
        self.save_prompt.notice.connect(lambda text: self.notice(self.current_view(), text))
        layout.addWidget(self.save_prompt)
        self.tabs = QTabWidget(self)
        self.tabs.setTabsClosable(True)
        self.tabs.setMovable(True)
        self.tabs.tabCloseRequested.connect(self.close_tab)
        self.tabs.currentChanged.connect(self.sync_address)
        self.login_actions = BrowserLoginActions(self)
        self.tabs.currentChanged.connect(self.login_actions.cancel)
        self.tabs.currentChanged.connect(self.sync_save_prompt)
        layout.addWidget(self.tabs, 1)
        self.status = QLabel('浏览器独立运行；隐藏面板不会退出网站。', self)
        self.status.setWordWrap(True)
        footer = QHBoxLayout()
        footer.addWidget(self.status, 1)
        self.retry_button = QPushButton('重试', self)
        self.retry_button.setAccessibleName('重新加载当前网页')
        self.retry_button.clicked.connect(self.retry_loading)
        self.retry_button.hide()
        footer.addWidget(self.retry_button)
        self.external_button = QPushButton('用系统浏览器打开', self)
        self.external_button.setAccessibleName('用系统浏览器打开当前网页')
        self.external_button.clicked.connect(self.open_in_system_browser)
        self.external_button.hide()
        footer.addWidget(self.external_button)
        self.downloads = DownloadsDialog(session, self)
        downloads_button = QPushButton('下载', self)
        downloads_button.setAccessibleName('查看浏览器下载')
        downloads_button.clicked.connect(self.downloads.show)
        footer.addWidget(downloads_button)
        credentials_button = QPushButton('网站账号', self)
        credentials_menu = QMenu(credentials_button)
        credentials_menu.addAction('填充当前网页登录账号', self.login_actions.fill_current)
        credentials_menu.addAction('管理已保存账号', self.open_credentials)
        credentials_button.setMenu(credentials_menu)
        footer.addWidget(credentials_button)
        layout.addLayout(footer)
        self.new_tab()
        self.takeover_filter = BrowserTakeover(self)

    def open_credentials(self):
        from .browser_credential_manager import CredentialManager
        from .browser_credential_vault import CredentialVault
        if self.credentials_dialog is None:
            vault = CredentialVault(self.session.preferences, self.session.owner,
                                    environment=self.session.environment)
            self.credentials_dialog = CredentialManager(vault, self)
        self.credentials_dialog.refresh()
        self.credentials_dialog.show()

    def library_error(self):
        self.notice(self.current_view(), '浏览器书签或主页设置不可用，请检查数据目录。')

    def open_address(self, url):
        self.address.setText(url)
        self.navigate()

    def open_home(self):
        try:
            self.open_address(self.library.home())
        except (ValueError, OSError, sqlite3.Error):
            self.library_error()

    def add_bookmark(self):
        url = self.current_view().url().toString() or 'about:blank'
        title, accepted = QInputDialog.getText(self, '添加或更新书签',
            '名称（网址仅保存在本机当前账号下）', text=(self.current_view().title() or '新书签')[:120])
        if not accepted:
            return
        try:
            self.library.save(title, url)
            self.notice(self.current_view(), '书签已保存。')
        except (ValueError, OSError, sqlite3.Error):
            self.library_error()

    def set_current_home(self):
        url = self.current_view().url().toString() or 'about:blank'
        if QMessageBox.question(self, '设置主页', '将当前页面设为本账号主页？新标签仍默认空白页。') != QMessageBox.StandardButton.Yes:
            return
        try:
            self.library.set_home(url)
            self.notice(self.current_view(), '主页已设置。')
        except (ValueError, OSError, sqlite3.Error):
            self.library_error()

    def remove_bookmark(self, url):
        if QMessageBox.question(self, '删除书签', '删除这条本地书签？不会修改网站内容。') != QMessageBox.StandardButton.Yes:
            return
        try:
            self.library.remove(url)
            self.notice(self.current_view(), '书签已删除。')
        except (ValueError, OSError, sqlite3.Error):
            self.library_error()

    def refresh_bookmarks(self):
        menu = self.bookmark_menu
        menu.clear()
        for submenu in self._bookmark_submenus:
            submenu.deleteLater()
        self._bookmark_submenus.clear()
        menu.addAction('添加或更新当前页书签', self.add_bookmark)
        menu.addAction('将当前页设为主页', self.set_current_home)
        menu.addSeparator()
        try:
            rows = self.library.bookmarks()
        except (ValueError, OSError, sqlite3.Error):
            menu.addAction('书签暂不可用').setEnabled(False)
            return
        if not rows:
            menu.addAction('尚无书签').setEnabled(False)
        for title, url in rows:
            entry = QMenu(title.replace('&', '&&'), menu)
            self._bookmark_submenus.append(entry)
            menu.addMenu(entry)
            entry.addAction('打开', lambda _checked=False, address=url: self.open_address(address))
            entry.addAction('删除', lambda _checked=False, address=url: self.remove_bookmark(address))

    def current_view(self):
        return self.tabs.currentWidget()

    def new_tab(self, *, blank=True):
        from .browser_credential_vault import CredentialVault
        page = self.session.new_page()
        self.task_leases.register(page)
        view = QWebEngineView(page, self)
        timer = QTimer(view)
        timer.setSingleShot(True)
        timer.setInterval(self.LOAD_TIMEOUT_MS)
        timer.timeout.connect(lambda: self.loading_timed_out(view))
        self.load_timers[view] = timer
        vault = CredentialVault(self.session.preferences, self.session.owner, environment=self.session.environment)
        self.login_captures[view] = LoginCapture(self.session, page, vault)
        index = self.tabs.addTab(view, '新标签页')
        page.blocked.connect(lambda message: self.security_blocked(view, message))
        page.newWindowRequested.connect(lambda request: self.open_popup(view, request))
        view.urlChanged.connect(lambda _url: self.url_changed(view))
        view.titleChanged.connect(lambda title: self.update_title(view, title))
        view.loadStarted.connect(lambda: self.loading(view, None))
        view.loadFinished.connect(lambda ok: self.loading(view, ok))
        self.tabs.setCurrentIndex(index)
        if blank:
            view.setUrl(QUrl('about:blank'))
        return view

    def sync_save_prompt(self, *_args):
        self.save_prompt.bind(self.login_captures.get(self.current_view()))

    def open_popup(self, source, request):
        if self.tabs.indexOf(source) < 0:
            return
        if not request.isUserInitiated():
            self.notice(source, '已阻止网页自动弹窗，请直接点击网页中的链接。')
            return
        try:
            navigation_url(request.requestedUrl().toString() or 'about:blank')
        except ValueError:
            self.notice(source, '已阻止不安全的弹窗地址。')
            return
        if self.tabs.count() >= 12:
            self.notice(source, '打开标签较多，请先关闭部分标签，再打开新窗口。')
            return
        current = self.current_view()
        view = self.new_tab(blank=False)
        request.openIn(view.page())
        if request.destination() == QWebEngineNewWindowRequest.DestinationType.InNewBackgroundTab:
            self.tabs.setCurrentWidget(current)

    def update_title(self, view, title):
        index = self.tabs.indexOf(view)
        if index >= 0:
            self.tabs.setTabText(index, (title or '新标签页')[:24])

    def loading(self, view, ok):
        timer = self.load_timers.get(view)
        if ok is None:
            view.setProperty('isLoading', True)
            view.setProperty('stoppedByUser', False)
            if view.property('noticeKind') in {'load', 'security', 'stopped', 'timeout'}:
                view.setProperty('notice', None)
                view.setProperty('noticeKind', None)
            view.setProperty('loadStatus', '正在加载网页…')
            view.setProperty('showRecovery', False)
            if timer is not None:
                timer.start()
        else:
            view.setProperty('isLoading', False)
            if timer is not None:
                timer.stop()
            if view.property('noticeKind') == 'timeout':
                view.setProperty('notice', None)
                view.setProperty('noticeKind', None)
            if view.property('stoppedByUser'):
                view.setProperty('loadStatus', '已停止加载。')
            elif ok:
                view.setProperty('loadStatus', '加载完成')
                view.setProperty('showRecovery', False)
            else:
                view.setProperty('loadStatus', '网页加载失败，请检查网络后重试。')
                view.setProperty('showRecovery', True)
        if view is self.current_view():
            self.show_status(view)

    def notice(self, view, message, *, kind=None):
        view.setProperty('notice', message)
        view.setProperty('noticeKind', kind)
        if view is self.current_view():
            self.show_status(view)

    def security_blocked(self, view, message):
        view.setProperty('showRecovery', False)
        self.notice(view, message, kind='security')

    def stop_loading(self):
        view = self.current_view()
        if view is None:
            return
        timer = self.load_timers.get(view)
        if timer is not None:
            timer.stop()
        view.setProperty('isLoading', False)
        view.setProperty('stoppedByUser', True)
        view.setProperty('showRecovery', True)
        self.notice(view, '已停止加载。', kind='stopped')
        view.stop()

    def loading_timed_out(self, view):
        if not view.property('isLoading'):
            return
        view.setProperty('showRecovery', True)
        self.notice(
            view,
            '网站长时间未完成加载，可能与内置浏览器不兼容。可重试或用系统浏览器打开。',
            kind='timeout',
        )

    def retry_loading(self):
        view = self.current_view()
        if view is None:
            return
        view.setProperty('notice', None)
        view.setProperty('noticeKind', None)
        view.setProperty('showRecovery', False)
        self.show_status(view)
        view.reload()

    def open_in_system_browser(self):
        view = self.current_view()
        if view is None:
            return
        try:
            url = navigation_url(view.url().toString())
        except ValueError:
            self.notice(view, '当前网址无法交给系统浏览器。', kind='load')
            return
        if not QDesktopServices.openUrl(url):
            self.notice(view, '系统浏览器打开失败。', kind='load')

    def show_status(self, view):
        self.status.setText(view.property('notice') or view.property('loadStatus') or '新标签页')
        show_recovery = bool(view.property('showRecovery'))
        self.retry_button.setVisible(show_recovery)
        self.external_button.setVisible(show_recovery)

    def remember_address(self, text):
        view = self.current_view()
        if view is not None:
            view.setProperty('addressDraft', text)

    def url_changed(self, view):
        if view is self.current_view():
            self.sync_address()

    def sync_address(self, *_args):
        view = self.current_view()
        if view is not None:
            draft = view.property('addressDraft')
            self.address.setText(draft if draft is not None else view.url().toString())
            self.show_status(view)

    def navigate(self):
        try:
            url = navigation_url(self.address.text())
        except ValueError:
            self.notice(self.current_view(), '网址不安全或格式不正确，请输入完整的 HTTP/HTTPS 地址。')
            return
        self.current_view().setProperty('addressDraft', None)
        self.current_view().setProperty('notice', None)
        self.current_view().setProperty('noticeKind', None)
        self.current_view().setUrl(url)

    def close_tab(self, index):
        import shiboken6
        self.login_actions.cancel()
        view = cast(QWebEngineView | None, self.tabs.widget(index))
        if view is None:
            return
        page = view.page()
        self.task_leases.unregister(page)
        capture = self.login_captures.pop(view, None)
        timer = self.load_timers.pop(view, None)
        if timer is not None:
            timer.stop()
        if capture is not None:
            capture.close()
        self.tabs.removeTab(index)
        view.stop()
        shiboken6.delete(view)
        if shiboken6.isValid(page):
            shiboken6.delete(page)
        if self.tabs.count() == 0:
            self.new_tab()

    def shutdown(self):
        import shiboken6
        self.takeover_filter.close()
        self.task_leases.close()
        self.login_actions.cancel()
        self.save_prompt.bind(None)
        for capture in self.login_captures.values():
            capture.close()
        self.login_captures.clear()
        for timer in self.load_timers.values():
            timer.stop()
        self.load_timers.clear()
        if self.credentials_dialog is not None:
            self.credentials_dialog.shutdown()
        self.downloads.shutdown()
        while self.tabs.count():
            view = cast(QWebEngineView, self.tabs.widget(0))
            self.tabs.removeTab(0)
            view.stop()
            shiboken6.delete(view)
        self.session.close()

    def hideEvent(self, event):
        self.login_actions.cancel()
        self.save_prompt.success.setChecked(False)
        super().hideEvent(event)
