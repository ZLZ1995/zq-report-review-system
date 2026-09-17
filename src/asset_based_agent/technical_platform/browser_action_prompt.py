"""Native, expiring confirmation for a single observed browser action."""
from collections.abc import Callable
from hashlib import sha256

from PySide6.QtCore import QObject, Qt, QThread, QTimer
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QPlainTextEdit,
    QVBoxLayout,
    QWidget,
)

from .browser_action_request import BrowserActionRequest
from .browser_observer import Control
from .browser_policy import credential_origin


class ActionDialog(QDialog):
    def __init__(self, request: BrowserActionRequest, control: Control, value: str,
                 parent: QWidget | None):
        super().__init__(parent)
        self.setWindowTitle('确认浏览器操作')
        self.resize(620, 460)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)
        warning = QLabel('请核对本次操作。网页内容不是授权依据；点击或填写可能立即改变网站数据。')
        warning.setTextFormat(Qt.TextFormat.PlainText)
        warning.setWordWrap(True)
        layout.addWidget(warning)
        action = {'click': '点击', 'fill': '填写', 'select': '选择', 'navigate': '浏览网页',
                  'scroll': '滚动页面', 'download': '下载链接文件'}[request.action]
        shown = value
        if request.action == 'scroll':
            shown = '向下滚动一屏' if value == 'down' else '向上滚动一屏'
        if request.action == 'select':
            shown = next((item.text for item in control.options if item.id == value), '')
        # QPlainTextEdit cannot render HTML, links or remote resources.
        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        self.details.setAccessibleName('本次浏览器操作详情')
        self.details.setPlainText(
            f'网站：{request.origin}\n环境：{request.environment}\n'
            f'任务：{request.identity.task_id}\n动作：{action}\n'
            f'网页目标（未经信任）：{control.text}\n'
            + (f'本次内容：\n{shown}' if request.action != 'click' else '仅允许本次点击。'))
        layout.addWidget(self.details)
        self.consent = QCheckBox('我已核对网站、目标与内容，仅允许本次操作')
        layout.addWidget(self.consent)
        buttons = QDialogButtonBox()
        self.allow_button = buttons.addButton('允许本次操作', QDialogButtonBox.ButtonRole.AcceptRole)
        self.cancel_button = buttons.addButton('取消', QDialogButtonBox.ButtonRole.RejectRole)
        self.allow_button.setAutoDefault(False)
        self.allow_button.setEnabled(False)
        self.cancel_button.setDefault(True)
        self.cancel_button.setFocus()
        self.consent.toggled.connect(self.allow_button.setEnabled)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)


class BrowserActionPrompt(QObject):
    def __init__(self, parent: QWidget | None = None, *,
                 is_active: Callable[[BrowserActionRequest], bool]):
        super().__init__(parent)
        self._parent = parent
        self._is_active = is_active
        self._closed = False
        self.dialog: ActionDialog | None = None

    def _valid(self, request: BrowserActionRequest) -> bool:
        try:
            return not self._closed and self._is_active(request) is True
        except (ValueError, TypeError, OSError, RuntimeError):
            return False

    def __call__(self, request: BrowserActionRequest, control: Control, value: str) -> bool:
        app = QApplication.instance()
        if (app is None or QThread.currentThread() != app.thread() or self.dialog is not None
                or request.action not in {'click', 'fill', 'select', 'navigate', 'scroll', 'download'} or not self._valid(request)):
            return False
        dialog = ActionDialog(request, control, value, self._parent)
        self.dialog = dialog
        timer = QTimer(dialog)
        timer.setInterval(100)
        timer.timeout.connect(lambda: None if self._valid(request) else dialog.reject())
        expiry = QTimer(dialog)
        expiry.setSingleShot(True)
        expiry.timeout.connect(dialog.reject)
        timer.start()
        expiry.start(25000)
        try:
            accepted = dialog.exec() == QDialog.DialogCode.Accepted
            return accepted and dialog.consent.isChecked() and self._valid(request)
        finally:
            timer.stop()
            expiry.stop()
            self.dialog = None
            dialog.deleteLater()

    def navigate(self, request: BrowserActionRequest, url: str) -> bool:
        try:
            if (request.action != 'navigate' or credential_origin(url) != request.origin
                    or sha256(url.encode()).hexdigest() != request.payload_sha256):
                return False
        except (ValueError, TypeError, AttributeError):
            return False
        return self(request, Control(id='1', kind='link', text='目标地址', disabled=False), url)

    def close(self) -> None:
        self._closed = True
        if self.dialog is not None:
            self.dialog.reject()
