"""Non-modal download list; saving always requires an explicit user choice."""
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from .browser_download_controller import BrowserDownloads, DownloadRecord
from .browser_downloads import validate_filename


class DownloadRow(QWidget):
    def __init__(self, key, controller, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)
        self.name = QLabel(self)
        self.name.setTextFormat(Qt.TextFormat.PlainText)
        self.name.setWordWrap(True)
        self.name.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.name)
        self.progress = QProgressBar(self)
        self.progress.setAccessibleName('文件下载进度')
        layout.addWidget(self.progress)
        footer = QHBoxLayout()
        self.status = QLabel(self)
        self.status.setWordWrap(True)
        footer.addWidget(self.status, 1)
        self.cancel = QPushButton('取消下载', self)
        self.cancel.clicked.connect(lambda: controller.cancel(key))
        footer.addWidget(self.cancel)
        layout.addLayout(footer)

    def update_record(self, record: DownloadRecord):
        self.name.setText(str(record.target.destination))
        running = record.status == 'running'
        self.cancel.setEnabled(running)
        labels = {'running': '正在下载', 'completed': '已完成',
                  'cancelled': '已取消，未交付文件', 'failed': '下载或交付失败，未交付文件'}
        text = f'{labels[record.status]} · {record.received:,} 字节'
        if record.total > 0:
            text += f' / {record.total:,} 字节'
        if record.cleanup_pending:
            text += '\n暂存待安全清理（不会作为正式文件交付）。'
        self.status.setText(text)
        if running and record.total <= 0:
            self.progress.setRange(0, 0)
        else:
            self.progress.setRange(0, 100)
            value = 100 if record.status == 'completed' else (
                min(99, record.received * 100 // record.total) if record.total > 0 else 0)
            self.progress.setValue(value)
        self.progress.setVisible(running or record.status == 'completed')


class DownloadsDialog(QDialog):
    def __init__(self, session, parent=None):
        super().__init__(parent)
        self.setWindowTitle('浏览器下载')
        self.resize(640, 420)
        self.setMinimumSize(420, 260)
        self.session = session
        self.controller = BrowserDownloads(session, self.choose_destination)
        self.controller.changed.connect(self.update_download)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)
        label = QLabel('保存到你选择的非系统盘位置；关闭此窗口不停止下载。', self)
        label.setWordWrap(True)
        layout.addWidget(label)
        self.message = QLabel('本次浏览器会话暂无下载。', self)
        self.message.setWordWrap(True)
        self.controller.rejected.connect(self.show_error)
        layout.addWidget(self.message)
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        content = QWidget(scroll)
        self.items = QVBoxLayout(content)
        self.items.setContentsMargins(0, 0, 0, 0)
        self.items.setSpacing(8)
        self.items.addStretch()
        scroll.setWidget(content)
        layout.addWidget(scroll, 1)
        close = QPushButton('关闭列表', self)
        close.clicked.connect(self.hide)
        layout.addWidget(close, alignment=Qt.AlignmentFlag.AlignRight)
        self.rows: dict[int, DownloadRow] = {}

    def choose_destination(self, name):
        try:
            validate_filename(name)
        except ValueError:
            name = 'download.bin'
        # Revalidate the current data root; never fall back to a system default.
        with self.session.preferences.use(self.session.owner) as layout:
            directory = layout.downloads / 'browser' / self.session.environment
            if directory.resolve() != directory or not directory.is_dir():
                raise ValueError('Download directory is unavailable')
            path, _ = QFileDialog.getSaveFileName(self, '确认下载位置（不覆盖已有文件）',
                                                str(directory / name))
        return Path(path) if path else None

    def show_error(self, message):
        self.message.setText(message)
        self.show()

    def update_download(self, key):
        if key not in self.rows:
            row = DownloadRow(key, self.controller, self)
            self.rows[key] = row
            self.items.insertWidget(0, row)
            self.message.setText('下载记录仅展示本次浏览器会话。')
            self.show()
        self.rows[key].update_record(self.controller.records[key])

    def shutdown(self):
        self.controller.close()
        self.hide()
