"""User-visible memory creation and provenance labels."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QTextEdit,
    QVBoxLayout,
)

SCOPE_LABELS = {"user": "用户", "project": "项目", "session": "会话"}
STATUS_LABELS = {"active": "生效中", "revoked": "已撤回"}


def memory_label(record) -> str:
    source = "用户明确确认" if record.source == "explicit_user" else "已核实成果"
    return (
        f"[{SCOPE_LABELS[record.scope]} · {STATUS_LABELS[record.status]}] "
        f"{record.key}\n{record.text}\n来源：{source} · 版本 {record.version}"
    )


class MemoryEditorDialog(QDialog):
    def __init__(self, *, allow_session: bool, parent=None):
        super().__init__(parent)
        self.setWindowTitle("添加已确认记忆")
        self.setMinimumWidth(520)
        layout = QVBoxLayout(self)
        notice = QLabel(
            "记忆只作为后续理解参考，不授予修改原件、上传资料或操作网页的权限。\n"
            "请勿粘贴客户原文、密码或隐藏工作表内容。"
        )
        notice.setWordWrap(True)
        layout.addWidget(notice)
        form = QFormLayout()
        self.scope = QComboBox()
        self.scope.addItem("当前项目", "project")
        if allow_session:
            self.scope.addItem("当前会话", "session")
        self.scope.addItem("当前账号", "user")
        self.key = QLineEdit()
        self.key.setPlaceholderText("例如：输出格式")
        self.text = QTextEdit()
        self.text.setPlaceholderText("例如：审核结论采用简洁表述")
        self.text.setMaximumHeight(120)
        form.addRow("适用范围", self.scope)
        form.addRow("记忆名称", self.key)
        form.addRow("确认内容", self.text)
        layout.addLayout(form)
        self.confirm = QCheckBox("我确认保存该内容，并知晓可随时撤回")
        layout.addWidget(self.confirm)
        self.error = QLabel("")
        self.error.setStyleSheet("color:#c62828")
        layout.addWidget(self.error)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _accept(self):
        if not self.confirm.isChecked():
            self.error.setText("需要明确勾选确认后才能保存。")
            return
        if not self.key.text().strip() or not self.text.toPlainText().strip():
            self.error.setText("请填写记忆名称和内容。")
            return
        self.accept()

    def value(self):
        return {
            "scope": self.scope.currentData(),
            "key": self.key.text().strip(),
            "text": self.text.toPlainText().strip(),
        }
