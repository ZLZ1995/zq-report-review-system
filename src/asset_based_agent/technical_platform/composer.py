"""Chat input shortcuts, scoped to the composer rather than the whole window."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QTextEdit


class ChatComposer(QTextEdit):
    send_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._composing = False

    def inputMethodEvent(self, event):
        self._composing = bool(event.preeditString())
        super().inputMethodEvent(event)

    def focusOutEvent(self, event):
        super().focusOutEvent(event)
        self._composing = False

    def keyPressEvent(self, event):
        if event.key() not in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            return super().keyPressEvent(event)
        # IME candidate confirmation and a held-down Enter must never submit.
        if self._composing or event.isAutoRepeat() or not self.isEnabled():
            event.accept()
            return
        modifiers = event.modifiers() & ~Qt.KeyboardModifier.KeypadModifier
        if modifiers == Qt.KeyboardModifier.AltModifier:
            self.textCursor().insertBlock()
            event.accept()
        elif modifiers == Qt.KeyboardModifier.NoModifier:
            event.accept()
            self.send_requested.emit()
        else:
            super().keyPressEvent(event)
