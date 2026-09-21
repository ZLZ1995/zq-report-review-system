"""Local credential management, deliberately without a password reveal action."""
import sqlite3

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .browser_credential_vault import CredentialVault


class CredentialManager(QDialog):
    def __init__(self, vault: CredentialVault, parent=None):
        super().__init__(parent)
        self.vault = vault
        self._closed = False
        self.setWindowTitle('网站账号管理')
        self.resize(640, 440)
        self.setMinimumSize(420, 320)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)
        description = QLabel('仅管理当前平台账号在本机保存的网站账号。\n'
                             '删除保存的账号不会退出网站；密码不会在此显示。', self)
        description.setWordWrap(True)
        layout.addWidget(description)
        tabs = QTabWidget(self)
        layout.addWidget(tabs, 1)
        account_page, policy_page = QWidget(tabs), QWidget(tabs)
        tabs.addTab(account_page, '已保存账号')
        tabs.addTab(policy_page, '不再询问的网站')
        accounts_layout, policy_layout = QVBoxLayout(account_page), QVBoxLayout(policy_page)
        self.accounts, self.blocked = QListWidget(account_page), QListWidget(policy_page)
        self.accounts.setAccessibleName('已保存的网站和用户名')
        self.blocked.setAccessibleName('不再询问保存密码的网站')
        self.accounts.setWordWrap(True)
        self.accounts.setSpacing(6)
        accounts_layout.addWidget(self.accounts)
        actions = QHBoxLayout()
        self.delete_button = QPushButton('删除保存的账号', account_page)
        self.never_button = QPushButton('不再询问此网站', account_page)
        self.delete_button.clicked.connect(self.delete_selected)
        self.never_button.clicked.connect(self.block_selected)
        actions.addWidget(self.delete_button)
        actions.addWidget(self.never_button)
        accounts_layout.addLayout(actions)
        self.agent_button = QPushButton('允许 Agent 用于登录任务', account_page)
        self.agent_button.clicked.connect(self.agent_selected)
        accounts_layout.addWidget(self.agent_button)
        policy_layout.addWidget(self.blocked)
        self.restore_button = QPushButton('恢复保存询问', policy_page)
        self.restore_button.clicked.connect(self.restore_selected)
        policy_layout.addWidget(self.restore_button)
        self.accounts.itemSelectionChanged.connect(self.update_buttons)
        self.blocked.itemSelectionChanged.connect(self.update_buttons)
        self.status = QLabel(self)
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        close = QPushButton('关闭', self)
        close.clicked.connect(self.hide)
        layout.addWidget(close, alignment=Qt.AlignmentFlag.AlignRight)
        self.update_buttons()

    def update_buttons(self):
        selected = bool(self.accounts.selectedItems()) and not self._closed
        self.delete_button.setEnabled(selected)
        self.never_button.setEnabled(selected)
        self.agent_button.setEnabled(selected)
        if selected:
            allowed = self.accounts.selectedItems()[0].data(Qt.ItemDataRole.UserRole + 1)[0]
            self.agent_button.setText('撤销 Agent 使用许可' if allowed else '允许 Agent 用于登录任务')
        self.restore_button.setEnabled(bool(self.blocked.selectedItems()) and not self._closed)

    def refresh(self):
        if self._closed:
            return
        self.accounts.clear()
        self.blocked.clear()
        try:
            entries, blocked = self.vault.entries(), self.vault.blocked_sites()
            for entry in entries:
                state = '已允许（仅限明确登录任务）' if entry.agent_allowed else '未允许'
                item = QListWidgetItem(f'{entry.origin}\n{entry.username}\nAgent 使用：{state}', self.accounts)
                item.setData(Qt.ItemDataRole.UserRole, (entry.key, entry.origin))
                item.setData(Qt.ItemDataRole.UserRole + 1, (entry.agent_allowed, entry.version, entry.username))
            self.blocked.addItems(blocked)
            self.status.setText(f'已保存 {len(entries)} 个账号；{len(blocked)} 个网站不再询问。')
        except (OSError, ValueError, sqlite3.Error):
            self.status.setText('无法读取本机网站账号，请检查数据目录或 Windows 用户。')
        self.accounts.setCurrentRow(-1)
        self.blocked.setCurrentRow(-1)
        self.update_buttons()

    def confirm(self, message):
        box = QMessageBox(self)
        box.setWindowTitle('确认网站账号设置')
        box.setTextFormat(Qt.TextFormat.PlainText)
        box.setText(message)
        box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        box.setDefaultButton(QMessageBox.StandardButton.No)
        return box.exec() == QMessageBox.StandardButton.Yes

    def change(self, message, action):
        if self._closed or not self.confirm(message) or self._closed:
            return
        try:
            action()
            self.refresh()
        except (OSError, ValueError, sqlite3.Error):
            self.status.setText('设置未完成，请检查本机数据目录后重试。')

    def delete_selected(self):
        selected = self.accounts.selectedItems()
        if selected:
            key, origin = selected[0].data(Qt.ItemDataRole.UserRole)
            self.change(f'删除 {origin} 下选中的本地账号凭据？\n不会删除网站账号或退出网站。',
                        lambda: self.vault.delete(key, confirmed=True))

    def block_selected(self):
        selected = self.accounts.selectedItems()
        if selected:
            _, origin = selected[0].data(Qt.ItemDataRole.UserRole)
            self.change(f'以后不再询问是否保存 {origin} 的密码？\n已保存的账号会保留。',
                        lambda: self.vault.set_prompt(origin, 'never', confirmed=True))

    def agent_selected(self):
        selected = self.accounts.selectedItems()
        if not selected:
            return
        key, origin = selected[0].data(Qt.ItemDataRole.UserRole)
        allowed, version, username = selected[0].data(Qt.ItemDataRole.UserRole + 1)
        if allowed:
            message = f'撤销 Agent 使用 {origin} 的账号 {username} 登录的许可？\n' \
                      '保存的密码和手动填充保留。已提交的登录或网站操作不能因此撤回。'
        else:
            message = f'允许 Agent 在你明确要求登录 {origin} 时使用账号 {username}？\n' \
                      '仅限该网站和该账号，不授权上传、提交业务或其他网站操作。\n密码只由本地组件填入，不交给大模型。'
        self.change(message, lambda: self.vault.set_agent_access(
            key, not allowed, confirmed=True, expected_version=version))

    def restore_selected(self):
        selected = self.blocked.selectedItems()
        if selected:
            origin = selected[0].text()
            self.change(f'恢复 {origin} 的密码保存询问？\n恢复询问不等于同意保存密码。',
                        lambda: self.vault.set_prompt(origin, 'ask', confirmed=True))

    def shutdown(self):
        self._closed = True
        for box in self.findChildren(QMessageBox):
            box.reject()
        self.update_buttons()
        self.hide()
