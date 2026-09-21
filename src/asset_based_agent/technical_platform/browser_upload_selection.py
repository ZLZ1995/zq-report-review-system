"""Choose this task's deliverables locally before exposing metadata to a model."""
from threading import Event

from PySide6.QtCore import Qt, QThread, QTimer
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
)

from .browser_upload_candidates import collect_upload_candidates


class CandidateWorker(QThread):
    def __init__(self, store, session, parent):
        super().__init__(parent)
        self.store, self.session = store, session
        self.cancel = Event()
        self.result = []
        self.failed = False

    def run(self):
        try:
            self.result = collect_upload_candidates(self.store, self.session, self.cancel)
        except Exception:  # noqa: BLE001 - no paths or raw exceptions in UI
            self.result = []
            self.failed = True


class UploadSelectionDialog(QDialog):
    def __init__(self, parent, store, session, active):
        super().__init__(parent)
        self.active = active
        self.selected = []
        self.loaded = False
        self.cancelled = False
        self.setWindowTitle('选择本次允许上传的成果')
        self.resize(660, 460)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)
        self.status = QLabel('正在后台校验当前会话成果，可随时取消。', self)
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.files = QListWidget(self)
        self.files.setWordWrap(True)
        self.files.setAccessibleName('本次成果范围，默认全部不选')
        self.files.itemChanged.connect(self._refresh)
        layout.addWidget(self.files)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, parent=self)
        ok = self.buttons.button(QDialogButtonBox.StandardButton.Ok)
        ok.setText('仅允许所选成果'); ok.setAutoDefault(False); ok.setEnabled(False)
        cancel = self.buttons.button(QDialogButtonBox.StandardButton.Cancel)
        cancel.setText('取消任务'); cancel.setDefault(True)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        self.timer = QTimer(self)
        self.timer.setInterval(100)
        self.timer.timeout.connect(self._refresh)
        self.finished.connect(self.timer.stop)
        self.worker = CandidateWorker(store, session, self)
        self.worker.finished.connect(self._loaded)
        self.timer.start()
        try:
            self.worker.start()
        except RuntimeError:
            self.worker.failed = True
            self._loaded()

    def valid(self):
        try:
            return not self.cancelled and self.active() is True
        except Exception:  # noqa: BLE001
            return False

    def _indices(self):
        return [i for i in range(self.files.count())
                if self.files.item(i).checkState() == Qt.CheckState.Checked]

    def _loaded(self):
        self.loaded = True
        if not self.valid():
            self.reject()
            return
        for record in self.worker.result:
            artifact = record['artifact']
            item = QListWidgetItem(f"{artifact['name']}  ·  {artifact['size']:,} 字节\n"
                                   f"任务 {record['source']['run_id']}  ·  SHA256 {artifact['sha256']}")
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Unchecked)
            self.files.addItem(item)
        self.status.setText('校验失败，请核对成果后重试。' if self.worker.failed else
            '没有可上传的有效成果，请先在本会话生成成果。' if not self.worker.result else
            '请选择本次指令涉及的成果（最多32个）。只向模型提供所选文件的名称、大小和版本；实际上传时仍需核对网站与业务对象。')
        self._refresh()

    def _refresh(self):
        if not self.valid():
            self.reject()
            return
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(
            self.loaded and not self.worker.isRunning() and 0 < len(self._indices()) <= 32)

    def accept(self):
        indices = self._indices()
        if self.valid() and self.loaded and not self.worker.isRunning() and 0 < len(indices) <= 32:
            self.selected = [self.worker.result[i] for i in indices]
            super().accept()

    def reject(self):
        self.cancelled = True
        self.selected = []
        self.worker.cancel.set()
        self.buttons.setEnabled(False)
        if self.worker.isRunning():
            self.status.setText('正在停止校验…不会执行上传。')
            return
        super().reject()

    def closeEvent(self, event):
        self.reject()
        if self.worker.isRunning():
            event.ignore()
        else:
            event.accept()


def select_upload_artifacts(parent, store, session, active):
    dialog = UploadSelectionDialog(parent, store, session, active)
    try:
        accepted = dialog.exec() == QDialog.DialogCode.Accepted
        return dialog.selected if accepted and dialog.valid() else []
    finally:
        dialog.timer.stop()
        dialog.deleteLater()
