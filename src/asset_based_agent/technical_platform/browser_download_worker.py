"""Background download verification workers: no Qt page or credential access."""
from pathlib import Path

from PySide6.QtCore import QThread

from .browser_download_artifacts import fingerprint_download


class DownloadVerificationWorker(QThread):
    def __init__(self, record, cancel, parent=None):
        super().__init__(parent)
        self.path, self.size = Path(record['path']), record['size']
        self.cancel = cancel
        self.result = None

    def run(self):
        try:
            self.result = fingerprint_download(self.path, self.size, self.cancel)
        except Exception:  # noqa: BLE001 - exception text could expose local paths
            self.result = None


class DownloadDeliveryWorker(QThread):
    """Native receipt/database and file verification; never settles the task."""
    def __init__(self, store, run_id, cancel, parent=None):
        super().__init__(parent)
        self.store, self.run_id, self.cancel = store, run_id, cancel
        self.result = None

    def run(self):
        from .browser_download_integrity import verify_download_delivery
        try:
            self.result = verify_download_delivery(self.store, self.run_id, self.cancel)
        except Exception:  # noqa: BLE001 - no path or exception text crosses the worker boundary
            self.result = None
