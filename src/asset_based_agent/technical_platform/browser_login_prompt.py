"""Local-only account choice. No credentials or account references reach the model."""
import sqlite3
import time

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QComboBox, QDialog, QDialogButtonBox, QLabel, QVBoxLayout


class LoginAccountDialog(QDialog):
    def __init__(self, parent, origin, accounts, active):
        super().__init__(parent)
        self.setWindowTitle('选择本次使用的网站账号')
        self.setMinimumWidth(520)
        self.active = active
        self.expires = time.monotonic() + 40
        self.selected = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)
        for text in (f'目标网站：{origin}',
                     '仅列出你已允许 Agent 使用的保存账号。\n本次只填入账号和密码，不自动提交登录；密码不会发送给大模型。'):
            label = QLabel(text, self)
            label.setTextFormat(Qt.TextFormat.PlainText)
            label.setWordWrap(True)
            layout.addWidget(label)
        self.accounts = QComboBox(self)
        self.accounts.setAccessibleName('本次使用的已授权账号')
        self.accounts.addItem('请选择账号…', None)
        for index, account in enumerate(accounts, 1):
            if account.origin == origin:
                self.accounts.addItem(f'{index}. {account.label}', account.key)
        layout.addWidget(self.accounts)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, parent=self)
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setText('仅填入此账号')
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setAutoDefault(False)
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(False)
        self.buttons.button(QDialogButtonBox.StandardButton.Cancel).setText('取消')
        self.buttons.button(QDialogButtonBox.StandardButton.Cancel).setDefault(True)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        self.accounts.currentIndexChanged.connect(self._refresh)
        layout.addWidget(self.buttons)
        self.timer = QTimer(self)
        self.timer.setInterval(100)
        self.timer.timeout.connect(self._refresh)
        self.finished.connect(self.timer.stop)
        self.timer.start()

    def _valid(self):
        try:
            return time.monotonic() < self.expires and self.active() is True
        except (ValueError, OSError, RuntimeError, sqlite3.Error):
            return False

    def _refresh(self):
        if not self._valid():
            self.reject()
            return
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(self.accounts.currentData() is not None)

    def accept(self):
        if self._valid() and self.accounts.currentData() is not None:
            self.selected = self.accounts.currentData()
            super().accept()
        else:
            self.reject()


def select_login_account(parent, origin, accounts, active):
    dialog = LoginAccountDialog(parent, origin, accounts, active)
    try:
        if not dialog._valid() or dialog.accounts.count() < 2:
            return None
        return dialog.selected if dialog.exec() == QDialog.DialogCode.Accepted and dialog._valid() else None
    finally:
        dialog.timer.stop()
        dialog.deleteLater()
