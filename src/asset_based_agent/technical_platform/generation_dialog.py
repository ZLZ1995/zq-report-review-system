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

from .generation import INPUT_ROLES, infer_financial_roles, validate_roles


class GenerationDialog(QDialog):
    def __init__(self, skill, files, output_root, parent=None):
        super().__init__(parent)
        self.skill, self.files, self.roles = skill, files, {}
        self.automatic = skill.id == 'valuation-detail-workbook-fill'
        self.setWindowTitle('确认生成资料及授权')
        self.resize(640, 360)
        layout = QVBoxLayout(self)
        analysis_note = ('模型联网识别已选资料；仅发送可见文本节选，按账户规则计费。\n'
                         if self.automatic else '本地按固定业务规则生成，不调用大模型。\n')
        label = QLabel(f'{skill.name}\n使用内置锁定模板，不允许选择或替换模板。\n' + analysis_note +
                       f'成果及临时数据：{output_root}/runs/<本轮任务>/\n'
                       '只生成副本，不覆盖原件；校验失败不交付正式文件。\n'
                       '未支持的来源布局会说明原因并停止，不猜数凑平。')
        label.setWordWrap(True)
        layout.addWidget(label)
        if skill.id == 'valuation-detail-workbook-fill':
            scope_note = QLabel('自动分析本轮已选文件，无需手动指定资料类型。'
                                '识别不明确或缺少必要证据时在对话中说明；不猜数、不修改原文件。')
            scope_note.setWordWrap(True)
            layout.addWidget(scope_note)
            office_note = QLabel('需安装 Microsoft Excel 或 WPS 表格（任意一种）。程序自动选择，'
                                 '只读计算生成副本；组件不可用或校验失败时不交付文件。')
            office_note.setWordWrap(True)
            layout.addWidget(office_note)
        form = QFormLayout()
        self.choices = {}
        for role, title, suffixes, required in ([] if self.automatic else INPUT_ROLES[skill.id]):
            choice = QComboBox()
            choice.addItem('请选择…' if required else '未提供', None)
            for item in files:
                if Path(item['name']).suffix.lower() in suffixes:
                    choice.addItem(item['name'], item['id'])
            form.addRow(title, choice)
            self.choices[role] = choice
        if skill.id == 'financial-brief-docx':
            try:
                inferred = infer_financial_roles(files)
                for role, identity in inferred.items():
                    self.choices[role].setCurrentIndex(self.choices[role].findData(identity))
            except (ValueError, OSError, KeyError):
                pass
        layout.addLayout(form)
        if self.automatic:
            inventory = QLabel('\n'.join(item['name'] for item in files))
            inventory.setWordWrap(True)
            layout.addWidget(inventory)
        self.consent = QCheckBox('允许本轮读取资料' + ('、联网识别可见文本' if self.automatic else '') +
                                '，并在项目目录生成新文件（不修改原件）')
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
        if self.automatic:
            self.roles = None
            self.accept()
            return
        roles = {key: choice.currentData() for key, choice in self.choices.items() if choice.currentData()}
        try:
            validate_roles(self.skill.id, self.files, roles)
        except ValueError as exc:
            QMessageBox.warning(self, '资料角色', str(exc))
            return
        self.roles = roles
        self.accept()
