"""Local, explicit Skill package management; no automatic execution or pip installs."""

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
)

from .skill_installation import SkillInstallation
from .skill_package import inspect_package


class SkillManagerDialog(QDialog):
    def __init__(self, store, parent=None):
        super().__init__(parent)
        self.manager = SkillInstallation(store)
        self.setWindowTitle("能力与 Skill")
        self.resize(760, 560)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)
        notice = QLabel("Agent 根据自然语言自动选择内置 Skill、外部 Skill 或原生能力，无需手动切换。\n"
                        "外部 ZIP 安装后默认停用，不执行包内脚本；所有文件能力默认只读原件。")
        notice.setWordWrap(True)
        layout.addWidget(notice)
        self.versions = QListWidget()
        self.versions.setAccessibleName("已安装的 Skill 版本")
        layout.addWidget(self.versions, 1)
        self.details = QTextEdit()
        self.details.setReadOnly(True)
        self.details.setAccessibleName("权限、依赖和完整性详情")
        layout.addWidget(self.details, 1)
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.status)
        actions = QHBoxLayout()
        self.action_buttons = {}
        for title, callback in (("安装外部 Skill…", self.install_package),
                                ("启用所选版本", self.activate_selected),
                                ("停用所选 Skill", self.disable_selected), ("关闭", self.accept)):
            button = QPushButton(title)
            button.setAutoDefault(False)
            button.clicked.connect(callback)
            actions.addWidget(button)
            self.action_buttons[title] = button
        layout.addLayout(actions)
        self.versions.currentRowChanged.connect(self.selection_changed)
        self.reload()

    def confirm(self, text):
        box = QMessageBox(self)
        box.setWindowTitle("确认 Skill 操作")
        box.setTextFormat(Qt.TextFormat.PlainText)
        box.setText(text)
        box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        box.setDefaultButton(QMessageBox.StandardButton.No)
        return box.exec() == QMessageBox.StandardButton.Yes

    def reload(self, selected=None):
        self.versions.clear()
        from .skills import BROWSER, BUILTINS
        for spec in BUILTINS:
            item = QListWidgetItem(f"{spec.name}  {spec.version} — 内置·自动路由")
            item.setData(Qt.ItemDataRole.UserRole, {'kind': 'builtin', 'spec': spec})
            self.versions.addItem(item)
        browser = QListWidgetItem(f"{BROWSER.name}  {BROWSER.version} — 原生能力·按需调用")
        browser.setData(Qt.ItemDataRole.UserRole, {'kind': 'native', 'spec': BROWSER})
        self.versions.addItem(browser)
        for row in self.manager.list_versions():
            state = "已启用·可由Agent选择" if row["enabled"] else "已安装·停用"
            item = QListWidgetItem(f"{row['name']}  {row['version']} — {state}")
            item.setData(Qt.ItemDataRole.UserRole, {'kind': 'external', **row})
            self.versions.addItem(item)
        if self.versions.count():
            self.versions.setCurrentRow(0)
        if selected is not None:
            for index in range(self.versions.count()):
                row = self.versions.item(index).data(Qt.ItemDataRole.UserRole)
                if (row.get('kind'), row.get('skill_id'), row.get('version')) == selected:
                    self.versions.setCurrentRow(index)
                    break

    def selected(self):
        item = self.versions.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def selection_changed(self):
        row = self.selected()
        if row is None:
            self.details.clear()
            return
        if row['kind'] != 'external':
            spec = row['spec']
            source = '平台原生能力' if row['kind'] == 'native' else '随客户端安装的内置 Skill'
            self.details.setPlainText(
                f"{spec.name}\nID：{spec.id}\n版本：{spec.version}\n来源：{source}\n"
                f"能力边界：{', '.join(sorted(spec.capabilities))}\n"
                "由 Agent 根据自然语言和本轮资料自动选择；不授予修改原件权限。"
            )
            self.action_buttons['启用所选版本'].setEnabled(False)
            self.action_buttons['停用所选 Skill'].setEnabled(False)
            return
        self.action_buttons['启用所选版本'].setEnabled(True)
        self.action_buttons['停用所选 Skill'].setEnabled(True)
        try:
            package = self.manager.load(row["skill_id"], row["version"])
            self.details.setPlainText(self.describe(package))
        except (ValueError, PermissionError, OSError) as exc:
            self.details.setPlainText(str(exc))

    @staticmethod
    def describe(package):
        info = package.manifest
        return (f"{info['name']}\nID：{info['id']}\n版本：{info['version']}\n"
                f"适配器：{info['adapter']}\n能力声明：{', '.join(info['capabilities'])}\n"
                f"依赖：{info['dependencies'] or '无'}\n"
                f"缺失或不兼容依赖：{', '.join(package.missing_dependencies) or '无'}\n"
                f"SHA256：{package.sha256}\n仅代表完整性校验，不代表发布者可信。\n"
                "启用后由Agent通过受支持的适配器使用规则；安装及启用不授予修改原件或执行脚本权限。")

    def install_package(self):
        path, _ = QFileDialog.getOpenFileName(self, "选择外部 Skill 包", "", "Skill 包 (*.zip)")
        if not path:
            return
        try:
            package = inspect_package(Path(path))
            if not self.confirm(self.describe(package) + "\n\n确认安装？安装后默认停用。"):
                return
            self.manager.install(Path(path), confirmed=True, expected_sha256=package.sha256)
            self.reload(('external', package.manifest['id'], package.manifest['version']))
            self.status.setText("已安装。请检查依赖后选择需要启用的版本。")
        except (ValueError, PermissionError, OSError) as exc:
            self.status.setText(str(exc))

    def activate_selected(self):
        self.change_selected(True)

    def disable_selected(self):
        self.change_selected(False)

    def change_selected(self, activate):
        row = self.selected()
        if row is None:
            self.status.setText("请先选择一个已安装的版本。")
            return
        if row['kind'] != 'external':
            self.status.setText('内置 Skill 与原生能力由平台版本管理，不能在此停用。')
            return
        action = "启用此版本（取代当前启用版本）" if activate else "停用此 Skill"
        if not self.confirm(f"{row['skill_id']} {row['version']}\n{action}？"):
            return
        try:
            if activate:
                self.manager.activate(row["skill_id"], row["version"], confirmed=True)
            else:
                self.manager.disable(row["skill_id"], confirmed=True)
            self.reload(('external', row['skill_id'], row['version']))
            self.status.setText("操作已保存；规则可用于后续任务，当前不会自动调用模型。")
        except (ValueError, PermissionError, OSError) as exc:
            self.status.setText(str(exc))
