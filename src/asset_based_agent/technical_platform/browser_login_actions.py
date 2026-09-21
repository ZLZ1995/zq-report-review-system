"""Explicit user interaction for saved login fill; not an Agent permission grant."""
import sqlite3
import weakref

import shiboken6
from PySide6.QtCore import QObject
from PySide6.QtWidgets import QDialog, QInputDialog

from .browser_credential_vault import CredentialVault
from .browser_policy import credential_origin
from .browser_trusted_login import TrustedLogin


class BrowserLoginActions(QObject):
    def __init__(self, panel):
        super().__init__(panel)
        self._panel = weakref.ref(panel)
        self.active = None
        self.dialog = None
        self._watched = None

    def panel(self):
        panel = self._panel()
        return panel if panel is not None and shiboken6.isValid(panel) else None

    def cancel(self, *_args):
        active, self.active = self.active, None
        dialog, self.dialog = self.dialog, None
        if dialog is not None:
            dialog.reject()
        if active is not None:
            active[1].close()
        page, self._watched = self._watched, None
        if page is not None and shiboken6.isValid(page):
            page.loadStarted.disconnect(self.cancel)
            page.urlChanged.disconnect(self.cancel)

    def _current(self, token, view):
        panel = self.panel()
        if isinstance(view, QObject) and not shiboken6.isValid(view):
            return False
        return (self.active is not None and self.active[0] is token and panel is not None
                and panel.current_view() is view and panel.session.owns_page(view.page()))

    def fill_current(self):
        self.cancel()
        panel = self.panel()
        if panel is None or panel.current_view() is None:
            return
        view, session = panel.current_view(), panel.session
        page = view.page()
        try:
            origin = credential_origin(page.url().toString())
            vault = CredentialVault(session.preferences, session.owner, environment=session.environment)
            accounts = [entry for entry in vault.entries() if entry.origin == origin]
            if not accounts:
                panel.notice(view, '当前 HTTPS 网站尚无已保存账号。')
                return
            bridge = TrustedLogin(session, page, vault)
        except (OSError, ValueError, sqlite3.Error):
            panel.notice(view, '无法填充：请确认当前为 HTTPS 登录页面且本机凭据可用。')
            return
        token = object()
        self.active = (token, bridge)
        self._watched = page
        page.loadStarted.connect(self.cancel)
        page.urlChanged.connect(self.cancel)

        def ready(ticket):
            if not self._current(token, view):
                return
            if ticket is None:
                self.cancel()
                panel.notice(view, '未识别到可安全填充的登录表单，请手动登录。')
                return
            dialog = QInputDialog(panel)
            self.dialog = dialog
            dialog.setWindowTitle('确认填充网站账号')
            dialog.setLabelText(f'网站：{origin}\n选择本次要填入的账号。\n仅填入账号和密码，不主动提交登录。')
            labels = [f'{index+1}. ' + ''.join(c if c.isprintable() else ' ' for c in entry.username)[:80]
                      for index, entry in enumerate(accounts)]
            dialog.setComboBoxItems(labels)
            dialog.setComboBoxEditable(False)
            dialog.setOkButtonText('确认填充')
            dialog.setCancelButtonText('取消')
            accepted = dialog.exec() == QDialog.DialogCode.Accepted
            chosen = dialog.textValue()
            self.dialog = None
            dialog.deleteLater()
            if not self._current(token, view):
                return
            if not accepted or chosen not in labels:
                self.cancel()
                return

            def finished(ok):
                if self._current(token, view):
                    self.cancel()
                    panel.notice(view, '已填入所选账号，请自行确认并登录。' if ok else
                                 '页面或表单已变化，未确认填充成功；请检查页面后重试。')

            bridge.fill(ticket, accounts[labels.index(chosen)].key, confirmed=True, callback=finished)

        bridge.probe(ready)
