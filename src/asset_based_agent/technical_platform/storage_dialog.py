"""Explicit, modal, background migration of platform data (not project files)."""
from functools import partial
from pathlib import Path

from PySide6.QtCore import Slot
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from ..report_review_app.workers.function_worker import FunctionWorker


class StorageDialog(QDialog):
    def __init__(self, preferences, owner: str, parent=None):
        super().__init__(parent)
        self.preferences = preferences
        self.owner = owner
        self.worker = None
        self.setWindowTitle('平台数据目录')
        self.setModal(True)
        self.resize(620, 300)
        layout = QVBoxLayout(self)
        self.location = QLabel(str(preferences.load(owner).data_root))
        self.location.setWordWrap(True)
        layout.addWidget(self.location)
        explanation = QLabel(
            '迁移当前账号的平台缓存、浏览器资料、凭据及更新暂存文件。\n'
            '项目资料、审核成果及外部 Skill 仍保留在各自项目目录，本操作不移动它们。\n'
            '复制并逐文件校验后才切换，原目录保留。请选择非系统盘的已有目录。'
        )
        explanation.setWordWrap(True)
        layout.addWidget(explanation)
        self.status = QLabel('迁移前请关闭使用此数据目录的其他客户端和浏览器。')
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.migrate_button = QPushButton('选择新目录并迁移')
        self.migrate_button.clicked.connect(self.migrate)
        layout.addWidget(self.migrate_button)
        self.close_button = QPushButton('关闭')
        self.close_button.clicked.connect(self.reject)
        layout.addWidget(self.close_button)

    def migrate(self):
        if self.worker is not None:
            return
        directory = QFileDialog.getExistingDirectory(self, '选择非系统盘目标目录')
        if not directory:
            return
        if QMessageBox.question(
            self, '确认迁移',
            '仅复制当前账号的平台数据。原目录保留，项目文件位置不变。\n'
            '迁移时请勿拔出磁盘或修改源文件；校验结束前不能关闭此窗口。\n'
            f'目标：{directory}\n确认开始？',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        ) != QMessageBox.StandardButton.Yes:
            return
        self.migrate_button.setEnabled(False)
        self.close_button.setEnabled(False)
        self.status.setText('正在复制并校验平台数据；校验成功前不会切换目录。')
        self.worker = FunctionWorker(
            partial(self.preferences.migrate, self.owner, Path(directory),
                    confirmed=True, consumers_closed=True), self,
        )
        self.worker.succeeded.connect(self.succeeded)
        self.worker.failed.connect(self.failed)
        self.worker.finished.connect(self.migration_finished)
        self.worker.start()

    @Slot(object)
    def succeeded(self, layout):
        self.location.setText(str(layout.data_root))
        self.status.setText('迁移已完成，已切换到新目录；原目录保留，项目资料未移动。')

    @Slot(str)
    def failed(self, _error):
        # Do not surface raw exception details or credential file names.
        self.status.setText(
            '迁移未完成，未切换目录。请检查目录占用、磁盘空间、路径和源文件是否变化。'
            '原目录保留；目标中的未启用副本也保留，不会覆盖或删除。'
        )

    @Slot()
    def migration_finished(self):
        self.worker.wait()
        self.worker.succeeded.disconnect(self.succeeded)
        self.worker.failed.disconnect(self.failed)
        self.worker.finished.disconnect(self.migration_finished)
        self.worker.deleteLater()
        self.worker = None
        self.migrate_button.setEnabled(True)
        self.close_button.setEnabled(True)

    def reject(self):
        if self.worker is None:
            super().reject()

    def closeEvent(self, event):
        if self.worker is not None:
            event.ignore()
        else:
            event.accept()
