"""Run one callable in a QThread and return its result."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QThread, Signal


class FunctionWorker(QThread):
    succeeded = Signal(object)
    failed = Signal(str)

    def __init__(self, function: Callable[[], Any], parent=None) -> None:
        super().__init__(parent)
        self.function = function

    def run(self) -> None:
        try:
            self.succeeded.emit(self.function())
        except Exception as exc:  # pragma: no cover - Qt thread boundary
            self.failed.emit(f"{type(exc).__name__}: {exc}")
