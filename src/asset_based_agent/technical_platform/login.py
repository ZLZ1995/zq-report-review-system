"""Non-blocking login and mandatory password change for the platform."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QFormLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
)

from ..report_review_app.workers.function_worker import FunctionWorker
from .session import PlatformSession


class PlatformLogin(QDialog):
    def __init__(self, service: PlatformSession, parent=None):
        super().__init__(parent)
        self.service = service
        self.result_payload = None
        self.worker = None
        self.changing = False
        self.setWindowTitle("登录 ZQ Workspace")
        self.setMinimumWidth(440)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 28, 28, 28)
        self.heading = QLabel("登录你的工作空间")
        self.heading.setStyleSheet("font-size:22px;font-weight:600;padding-bottom:18px")
        layout.addWidget(self.heading)
        form = QFormLayout()
        self.username = QLineEdit()
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.new_password = QLineEdit()
        self.new_password.setEchoMode(QLineEdit.EchoMode.Password)
        self.new_password.setPlaceholderText("客户密码：8–16位数字或数字+英文")
        self.confirm_password = QLineEdit()
        self.confirm_password.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow("账号", self.username)
        form.addRow("密码", self.password)
        self.new_label, self.confirm_label = QLabel("新密码"), QLabel("确认新密码")
        form.addRow(self.new_label, self.new_password)
        form.addRow(self.confirm_label, self.confirm_password)
        for widget in (
            self.new_label,
            self.new_password,
            self.confirm_label,
            self.confirm_password,
        ):
            widget.hide()
        layout.addLayout(form)
        self.error = QLabel()
        self.error.setWordWrap(True)
        self.error.setStyleSheet("color:#b42318")
        layout.addWidget(self.error)
        self.submit_button = QPushButton("登录")
        self.submit_button.clicked.connect(self.submit)
        self.password.returnPressed.connect(self.submit)
        layout.addWidget(self.submit_button)
        self.offline_button = QPushButton("离线进入本地工作区（不调用模型）")
        self.offline_button.setVisible(parent is None)
        self.offline_button.clicked.connect(self.enter_offline)
        layout.addWidget(self.offline_button)
        layout.addWidget(QLabel("账号由管理员创建；忘记密码请联系管理员。"))

    def enter_offline(self):
        if self.worker or self.parent() is not None:
            return
        self.password.clear()
        self.new_password.clear()
        self.confirm_password.clear()
        self.result_payload = {"offline": True, "owner": "offline-local", "models": []}
        self.accept()

    def submit(self):
        if self.worker:
            return
        username, password = self.username.text().strip(), self.password.text()
        new = self.new_password.text()
        if not username or not password:
            self.error.setText("请输入账号和密码。")
            return
        if self.changing and (not new or new != self.confirm_password.text()):
            self.error.setText("请输入一致的新密码。")
            return
        changing = self.changing
        self.worker = FunctionWorker(
            lambda: (
                self.service.change_password(password, new)
                if changing
                else self.service.login(username, password)
            ),
            self,
        )
        self.submit_button.setEnabled(False)
        self.error.clear()
        self.worker.succeeded.connect(self.succeeded)
        self.worker.failed.connect(self.failed)
        self.worker.finished.connect(self.worker_finished)
        self.worker.start()

    def succeeded(self, result):
        self.password.clear()
        self.new_password.clear()
        self.confirm_password.clear()
        if result.get("must_change_password"):
            self.changing = True
            self.username.setReadOnly(True)
            self.heading.setText("首次登录，请修改临时密码")
            for widget in (
                self.new_label,
                self.new_password,
                self.confirm_label,
                self.confirm_password,
            ):
                widget.show()
            self.submit_button.setText("修改密码并进入")
            self.password.setPlaceholderText("重新输入临时密码")
        else:
            self.result_payload = result

    def failed(self, _detail):
        self.password.clear()
        self.new_password.clear()
        self.confirm_password.clear()
        safe_messages = {
            "本机安全凭据保存失败，请检查 Windows 凭据管理器。",
            "客户密码须为8–16位纯数字或数字与英文字母组合，区分大小写。",
            "管理员密码须为12–256位。",
            "当前密码错误。",
            "用户名或密码错误，或登录已失效。",
            "管理员尚未配置可用模型",
            "无法连接审核服务，请检查网络。",
        }
        # FunctionWorker prefixes exceptions with their type. Only allow known messages.
        message = _detail.partition(": ")[2] if ": " in _detail else _detail
        self.error.setText(message if message in safe_messages else "操作未完成，请检查密码要求、服务端模型配置和网络。")

    def worker_finished(self):
        self.worker.function = lambda: None  # release password-bearing closure
        self.worker.deleteLater()
        self.worker = None
        self.submit_button.setEnabled(True)
        if self.result_payload is not None:
            self.accept()

    def reject(self):
        if not self.worker:
            super().reject()
