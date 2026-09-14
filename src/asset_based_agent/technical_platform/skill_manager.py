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
        self.setWindowTitle("外部 Skill 管理")
        self.resize(760, 560)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)
        notice = QLabel("安装本地 Skill ZIP 包 · 默认停用 · 不执行包内脚本\n当前安装管理已开放，外部 Skill 尚未接入任务执行。")
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
        for title, callback in (("安装外部 Skill…", self.install_package),
                                ("启用所选版本", self.activate_selected),
                                ("停用所选 Skill", self.disable_selected), ("关闭", self.accept)):
            button = QPushButton(title)
            button.setAutoDefault(False)
            button.clicked.connect(callback)
            actions.addWidget(button)
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

    def reload(self):
        self.versions.clear()
        for row in self.manager.list_versions():
            state = "已启用（尚未接入任务执行）" if row["enabled"] else "已安装·停用"
            item = QListWidgetItem(f"{row['name']}  {row['version']} — {state}")
            item.setData(Qt.ItemDataRole.UserRole, row)
            self.versions.addItem(item)
        if self.versions.count():
            self.versions.setCurrentRow(0)

    def selected(self):
        item = self.versions.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def selection_changed(self):
        row = self.selected()
        if row is None:
            self.details.clear()
            return
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
                "尚未接入任务执行；安装及启用不授予修改原件或执行脚本权限。")

    def install_package(self):
        path, _ = QFileDialog.getOpenFileName(self, "选择外部 Skill 包", "", "Skill 包 (*.zip)")
        if not path:
            return
        try:
            package = inspect_package(Path(path))
            if not self.confirm(self.describe(package) + "\n\n确认安装？安装后默认停用。"):
                return
            self.manager.install(Path(path), confirmed=True, expected_sha256=package.sha256)
            self.reload()
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
        action = "启用此版本（取代当前启用版本）" if activate else "停用此 Skill"
        if not self.confirm(f"{row['skill_id']} {row['version']}\n{action}？"):
            return
        try:
            if activate:
                self.manager.activate(row["skill_id"], row["version"], confirmed=True)
            else:
                self.manager.disable(row["skill_id"], confirmed=True)
            self.reload()
            self.status.setText("操作已保存；尚未接入任务执行，不会自动调用模型。")
        except (ValueError, PermissionError, OSError) as exc:
            self.status.setText(str(exc))
