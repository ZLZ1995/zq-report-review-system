"""Local success/consent prompt. Never displays or exports a website password."""
import sqlite3

import shiboken6
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .browser_login_capture import LoginCapture


class LoginSavePrompt(QWidget):
    notice = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.capture: LoginCapture | None = None
        self.replace_id: str | None = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)
        self.label = QLabel(self)
        self.label.setTextFormat(Qt.TextFormat.PlainText)
        self.label.setWordWrap(True)
        layout.addWidget(self.label)
        self.success = QCheckBox('我确认此网站已成功登录', self)
        self.success.toggled.connect(self._enable)
        layout.addWidget(self.success)
        self.save_button = QPushButton('保存账号密码', self)
        self.save_button.clicked.connect(self._save)
        self.later = QPushButton('暂不保存', self)
        self.later.clicked.connect(self._discard)
        self.never = QPushButton('此网站不再询问', self)
        self.never.clicked.connect(self._never)
        actions = QHBoxLayout()
        for button in (self.save_button, self.later, self.never):
            button.setMinimumHeight(32)
            actions.addWidget(button)
        layout.addLayout(actions)
        self.hide()

    def bind(self, capture: LoginCapture | None):
        if self.capture is not None and shiboken6.isValid(self.capture):
            self.capture.changed.disconnect(self.refresh)
        self.capture = capture
        if capture is not None:
            capture.changed.connect(self.refresh)
        self.refresh()

    def refresh(self):
        self.success.setChecked(False)
        self.replace_id = None
        capture = self.capture
        if capture is None or not shiboken6.isValid(capture) or capture.pending is None:
            self.hide()
            return
        try:
            matches = [entry for entry in capture.vault.entries()
                       if entry.origin == capture.origin and entry.username == capture.username]
            self.replace_id = matches[0].key if matches else None
        except (OSError, ValueError, sqlite3.Error):
            capture.discard()
            self.notice.emit('网站账号存储暂不可用，请检查数据目录。')
            return
        username = ''.join(c for c in capture.username if c.isprintable())[:80]
        self.label.setText(f'保存本次登录账号？\n网站：{capture.origin}\n账号：{username}\n'
                           '请先核对网页登录结果；登录失败请选“暂不保存”。仅加密保存在本机，2分钟后失效。')
        self.save_button.setText('更新已保存密码' if self.replace_id else '保存账号密码')
        self._enable()
        self.show()

    def _enable(self, *_args):
        capture = self.capture
        page = capture._live() if capture is not None and shiboken6.isValid(capture) else None
        self.save_button.setEnabled(bool(self.success.isChecked() and page is not None
                                         and not page.isLoading() and capture is not None and capture.pending is not None))

    def _discard(self):
        if self.capture is not None and shiboken6.isValid(self.capture):
            self.capture.discard()

    def _save(self):
        capture = self.capture
        if capture is None or not shiboken6.isValid(capture) or not self.success.isChecked():
            return
        try:
            capture.save(confirmed=True, login_succeeded=True, replace_id=self.replace_id)
            self.notice.emit('网站账号已加密保存在本机；这不会授予 Agent 自动使用权限。')
        except (OSError, ValueError, sqlite3.Error):
            self.notice.emit('网站账号未保存，请重新登录后再试；原保存记录未被替换。')

    def _never(self):
        capture = self.capture
        if capture is None or not shiboken6.isValid(capture) or capture.pending is None:
            return
        try:
            capture.vault.set_prompt(capture.origin, 'never', confirmed=True)
            self.notice.emit('此网站不再询问；可在网站账号管理中恢复。')
        except (OSError, ValueError, sqlite3.Error):
            self.notice.emit('未能保存询问设置，请检查数据目录。')
        finally:
            capture.discard()
