"""Account login window supporting local migration and remote product modes."""

from __future__ import annotations

from typing import Protocol

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QFormLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..branding import APPLICATION_NAME
from ..services.auth_service import (
    AuthConfigurationError,
    AuthenticationError,
)
from ..workers.function_worker import FunctionWorker


class LoginAuthenticator(Protocol):
    def authenticate(self, username: str, password: str) -> dict[str, str]: ...


class LoginWindow(QMainWindow):
    login_succeeded = Signal(object)

    def __init__(self, auth_service: LoginAuthenticator, parent=None) -> None:
        super().__init__(parent)
        self.auth_service = auth_service
        self.login_worker: FunctionWorker | None = None
        self.setWindowTitle(f"{APPLICATION_NAME} - 登录")
        self.setMinimumSize(460, 300)
        self._build_ui()

    def _build_ui(self) -> None:
        container = QWidget()
        layout = QVBoxLayout(container)
        title = QLabel(APPLICATION_NAME)
        title.setStyleSheet("font-size: 22px; font-weight: 600; color: #243447;")
        layout.addWidget(title)

        form = QFormLayout()
        self.username_input = QLineEdit()
        self.password_input = QLineEdit()
        self.password_input.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow("用户名", self.username_input)
        form.addRow("密码", self.password_input)
        layout.addLayout(form)

        self.error_label = QLabel()
        self.error_label.setStyleSheet("color: #b42318;")
        self.error_label.setWordWrap(True)
        layout.addWidget(self.error_label)

        self.login_button = QPushButton("登录")
        self.login_button.clicked.connect(self._login)
        self.password_input.returnPressed.connect(self._login)
        layout.addWidget(self.login_button)
        layout.addStretch(1)
        self.setCentralWidget(container)

    def _login(self) -> None:
        if getattr(self.auth_service, "is_remote", False):
            self._login_remote()
            return
        try:
            session = self.auth_service.authenticate(
                self.username_input.text(),
                self.password_input.text(),
            )
        except (AuthenticationError, AuthConfigurationError) as exc:
            self.error_label.setText(str(exc))
            return
        self.error_label.clear()
        self.password_input.clear()
        self.login_succeeded.emit(session)

    def _login_remote(self) -> None:
        if self.login_worker is not None and self.login_worker.isRunning():
            return
        username = self.username_input.text()
        password = self.password_input.text()
        self.login_button.setEnabled(False)
        self.login_button.setText("正在登录...")
        self.error_label.clear()
        self.login_worker = FunctionWorker(
            lambda: self.auth_service.authenticate(username, password),
            self,
        )
        self.login_worker.succeeded.connect(self._remote_login_succeeded)
        self.login_worker.failed.connect(self._remote_login_failed)
        self.login_worker.start()

    def _remote_login_succeeded(self, session: object) -> None:
        self._reset_login_button()
        self.password_input.clear()
        self.login_succeeded.emit(session)

    def _remote_login_failed(self, _detail: str) -> None:
        self._reset_login_button()
        self.password_input.clear()
        self.error_label.setText("登录失败，请检查账号、密码和网络连接。")

    def _reset_login_button(self) -> None:
        self.login_button.setEnabled(True)
        self.login_button.setText("登录")
