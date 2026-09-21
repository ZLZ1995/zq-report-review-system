"""Native per-action consent; website/model text is rendered as plain text."""
import time

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QPlainTextEdit,
    QVBoxLayout,
)

from ..browser_contracts import UploadArtifact
from .browser_policy import credential_origin


class UploadDialog(QDialog):
    def __init__(self, parent, origin, object_label, field_label, artifact, active):
        super().__init__(parent)
        artifact = UploadArtifact.model_validate(artifact)
        if credential_origin(origin) != origin:
            raise ValueError('Upload requires canonical origin')
        self.active = active
        self.expires = time.monotonic() + 40
        self.setWindowTitle('确认本次成果上传')
        self.resize(620, 440)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)
        self.details = QPlainTextEdit(self)
        self.details.setReadOnly(True)
        self.details.setAccessibleName('本次上传目标与成果版本')
        self.details.setPlainText(f'目标网站：{origin}\n\n业务对象（请核对）：{object_label}\n'
            f'页面控件：{field_label}\n\n成果：{artifact.name}\n大小：{artifact.size:,} 字节\n'
            f'SHA256：{artifact.sha256}\n\n仅上传此成果的校验副本，不上传原始资料。'
            '\n网页可能在选择文件后自动提交；停止任务不能撤销网站已接收的数据。'
            '\n文件交给网页不代表业务成功，后续仍需核对网站回执。')
        layout.addWidget(self.details)
        self.consent = QCheckBox('我已核对网站、业务对象及成果，允许本次上传', self)
        self.consent.toggled.connect(self._refresh)
        layout.addWidget(self.consent)
        self.effect_consent = None
        if origin == 'https://zhongqinoa01.com':
            self.details.appendPlainText(
                '\nOA特别提示：上传可能替换同工单、同分类、同轮次的当前文件版本。'
                '此处未确认当前槽位为空；不允许替换时请取消并先核对。'
                '本次仅授权文件上传，不授权提交审核、删除或审批。')
            self.effect_consent = QCheckBox('我已核对当前资料包，并允许本次上传可能产生的版本替换', self)
            self.effect_consent.toggled.connect(self._refresh)
            layout.addWidget(self.effect_consent)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, self)
        ok = self.buttons.button(QDialogButtonBox.StandardButton.Ok)
        ok.setText('上传此成果副本'); ok.setAutoDefault(False); ok.setEnabled(False)
        cancel = self.buttons.button(QDialogButtonBox.StandardButton.Cancel)
        cancel.setText('取消'); cancel.setDefault(True)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        self.timer = QTimer(self)
        self.timer.setInterval(100)
        self.timer.timeout.connect(self._refresh)
        self.finished.connect(self.timer.stop)
        self.timer.start()

    def valid(self):
        try:
            return time.monotonic() < self.expires and self.active() is True
        except Exception:  # noqa: BLE001 - expired native context must close without leaking errors
            return False

    def _refresh(self):
        if not self.valid():
            self.reject()
        else:
            self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(self.consented())

    def consented(self):
        return self.consent.isChecked() and (self.effect_consent is None or self.effect_consent.isChecked())

    def accept(self):
        if self.valid() and self.consented():
            super().accept()
        else:
            self.reject()


def confirm_upload(parent, observation, proposal, artifact, active):
    control = next((c for c in observation.controls if c.id == proposal.target), None)
    if control is None or control.kind != 'file' or control.disabled:
        return False
    dialog = UploadDialog(parent, observation.origin, proposal.object_label, control.text, artifact, active)
    try:
        return (dialog.valid() and dialog.exec() == QDialog.DialogCode.Accepted and dialog.valid())
    finally:
        dialog.timer.stop()
        dialog.deleteLater()
