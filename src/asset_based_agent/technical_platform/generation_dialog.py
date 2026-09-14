"""Bind selected project files to generator roles and obtain scoped consent."""

from pathlib import Path

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QMessageBox,
    QVBoxLayout,
)

from .generation import INPUT_ROLES, validate_roles


class GenerationDialog(QDialog):
    def __init__(self, skill, files, output_root, parent=None):
        super().__init__(parent)
        self.skill, self.files, self.roles = skill, files, {}
        self.setWindowTitle('确认生成资料及授权')
        self.resize(640, 360)
        layout = QVBoxLayout(self)
        label = QLabel(f'{skill.name}\n使用内置锁定模板，不允许选择或替换模板。\n本地按固定业务规则生成，不调用大模型。\n'
                       f'成果及临时数据：{output_root}/runs/<本轮任务>/\n'
                       '只生成副本，不覆盖原件；校验失败不交付正式文件。\n'
                       '未支持的来源布局会说明原因并停止，不猜数凑平。')
        label.setWordWrap(True)
        layout.addWidget(label)
        form = QFormLayout()
        self.choices = {}
        for role, title, suffixes, required in INPUT_ROLES[skill.id]:
            choice = QComboBox()
            choice.addItem('请选择…' if required else '未提供', None)
            for item in files:
                if Path(item['name']).suffix.lower() in suffixes:
                    choice.addItem(item['name'], item['id'])
            form.addRow(title, choice)
            self.choices[role] = choice
        layout.addLayout(form)
        self.consent = QCheckBox('允许本轮读取上述资料，并在项目目录生成新文件（不修改原件）')
        layout.addWidget(self.consent)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText('确认并生成')
        buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(False)
        self.consent.toggled.connect(buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled)
        buttons.accepted.connect(self.confirm)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def confirm(self):
        if not self.consent.isChecked():
            return
        roles = {key: choice.currentData() for key, choice in self.choices.items() if choice.currentData()}
        try:
            validate_roles(self.skill.id, self.files, roles)
        except ValueError as exc:
            QMessageBox.warning(self, '资料角色', str(exc))
            return
        self.roles = roles
        self.accept()
