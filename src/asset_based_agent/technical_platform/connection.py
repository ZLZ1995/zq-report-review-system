"""Asynchronous network probes; grace deadline is checked on the UI thread."""

from __future__ import annotations

import time

from PySide6.QtCore import QObject, QTimer, Signal

from ..report_review_app.services.remote_auth_service import (
    NetworkUnavailable,
    RemoteAuthenticationError,
)
from ..report_review_app.workers.function_worker import FunctionWorker
from .session import ConnectionState


class ConnectionMonitor(QObject):
    changed = Signal(str)
    balance = Signal(str)
    expired = Signal()

    def __init__(self, client, parent=None):
        super().__init__(parent)
        self.client, self.state = client, ConnectionState()
        self.worker = None
        self.next_probe = 0.0
        self.timer = QTimer(self)
        self.timer.setInterval(500)
        self.timer.timeout.connect(self.tick)

    def tick(self):
        before = self.state.state
        state = self.state.observe("pending", time.monotonic())
        if state == "terminated":
            self.timer.stop()
            if before != "terminated":
                self.expired.emit()
            return
        if self.worker or time.monotonic() < self.next_probe:
            return
        self.worker = FunctionWorker(self.probe, self)
        self.worker.succeeded.connect(self.observed)
        self.worker.failed.connect(lambda _: self.observed({"outcome": "offline"}))
        self.worker.finished.connect(self.finished)
        self.worker.start()

    def probe(self):
        try:
            self.client.heartbeat()
            balance = self.client.get_balance()
            return {"outcome": "ok", "balance": balance["balance"]}
        except NetworkUnavailable:
            return {"outcome": "offline"}
        except RemoteAuthenticationError:
            return {"outcome": "revoked"}

    def observed(self, result):
        state = self.state.observe(result["outcome"], time.monotonic())
        self.changed.emit(state)
        if state == "connected":
            self.balance.emit(result["balance"])
        if state == "terminated":
            self.timer.stop()
            self.expired.emit()
        self.next_probe = time.monotonic() + (10 if state == "connected" else 1)

    def finished(self):
        self.worker.deleteLater()
        self.worker = None

    def refresh(self):
        self.next_probe = 0
