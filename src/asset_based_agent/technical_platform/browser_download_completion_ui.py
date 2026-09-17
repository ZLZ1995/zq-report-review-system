"""GUI lifecycle for native download integrity verification and user confirmation."""
import sqlite3

from PySide6.QtCore import QCoreApplication, QEventLoop, QThread, QTimer
from PySide6.QtWidgets import QDialog

from .browser_completion import CompletionDialog
from .browser_download_completion import confirm_download_delivery
from .browser_download_worker import DownloadDeliveryWorker
from .browser_task_spec import browser_execution_goal
from .permissions import PermissionService


def verify_download_completion(host, detail, *, confirm, is_current=lambda: True):
    app = QCoreApplication.instance()
    if app is None or QThread.currentThread() != app.thread() or host.runtime is None:
        return None
    runtime = host.runtime

    def active():
        try:
            PermissionService(host.store).verify(host.run_id)
            binding = runtime.lease.binding
            return (not host.cancel.is_set() and is_current() is True
                    and host.runtime is runtime and binding.owner == host.store.owner
                    and binding.task_id == host.run_id and runtime.authorized() is True
                    and runtime.leases.valid(runtime.lease))
        except (ValueError, OSError, RuntimeError, KeyError, sqlite3.Error):
            return False

    if not active():
        return None
    # No QObject parent: a window closing must not destroy a running QThread.
    # Keep this local reference until finished; cancellation stays cooperative.
    worker = DownloadDeliveryWorker(host.store, host.run_id, host.cancel)
    wait = QEventLoop()
    worker.finished.connect(wait.quit)
    guard = QTimer()
    guard.timeout.connect(lambda: None if active() else host.cancel.set())
    guard.start(100)
    try:
        worker.start()
        while worker.isRunning():
            wait.exec()
        manifest = worker.result
    finally:
        guard.stop()
        # The event loop only returns on actual worker exit, not on cancellation.
        worker.deleteLater()
    if manifest is None or not active():
        return None
    return confirm_download_delivery(host.store, host.run_id, host.cancel, manifest, detail,
                                     confirm=confirm, is_current=active)


class DownloadCompletionDialog(CompletionDialog):
    def __init__(self, snapshot, detail, parent=None):
        super().__init__(snapshot, detail, parent)
        self.setWindowTitle('核对下载交付')
        self.details.setAccessibleName('下载目标和已校验的文件')
        files = '\n\n'.join(
            f"{item['name']}\n来源：{item['origin']}\n大小：{item['size']} bytes\nSHA256：{item['sha256']}"
            for item in detail['files'])
        self.details.setPlainText('\n\n'.join([
            '已核验本地文件完整性；请自行确认这些文件满足目标。此确认不证明网站写入成功。',
            '本轮目标：\n' + browser_execution_goal(snapshot),
            '模型说明（待核对）：\n' + detail['summary'],
            '已下载文件：\n' + files]))
        self.consent.setText('我已核对文件，确认满足本轮下载目标')
        self.accept_button.setText('确认下载交付')


def confirm_download_result(parent, snapshot, detail, active):
    if not active():
        return False
    dialog = DownloadCompletionDialog(snapshot, detail, parent)
    guard = QTimer(dialog)
    guard.timeout.connect(lambda: None if active() else dialog.reject())
    expiry = QTimer(dialog)
    expiry.setSingleShot(True)
    expiry.timeout.connect(dialog.reject)
    guard.start(100)
    expiry.start(120000)
    try:
        return dialog.exec() == QDialog.DialogCode.Accepted and dialog.consent.isChecked() and active()
    finally:
        guard.stop()
        expiry.stop()
        dialog.deleteLater()
