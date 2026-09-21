import os

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QInputMethodEvent, QKeyEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from asset_based_agent.technical_platform.app import PlatformWindow
from asset_based_agent.technical_platform.store import PlatformStore


@pytest.mark.parametrize('key', [Qt.Key.Key_Return, Qt.Key.Key_Enter])
def test_enter_sends_and_alt_enter_inserts_newline(tmp_path, key):
    app = QApplication.instance() or QApplication([])
    window = PlatformWindow(PlatformStore(tmp_path / 'state.db', 'tester'))
    calls = []
    window.submit = lambda: calls.append(window.composer.toPlainText())
    # The real send button already has its original bound slot; observe click behavior.
    window.send.clicked.disconnect()
    window.send.clicked.connect(window.submit)
    window.show()
    window.composer.setFocus()
    app.processEvents()
    try:
        window.composer.setPlainText('审核报告')
        window.composer.moveCursor(window.composer.textCursor().MoveOperation.End)
        QTest.keyClick(window.composer, key, Qt.KeyboardModifier.AltModifier)
        assert window.composer.toPlainText() == '审核报告\n'
        assert not calls
        QTest.keyClick(window.composer, key)
        assert calls == ['审核报告\n']
        assert window.composer.toPlainText() == '审核报告\n'
        window.set_busy(True)
        QTest.keyClick(window.composer, key)
        assert len(calls) == 1
    finally:
        window.close()


def test_ime_composition_and_auto_repeat_do_not_send(tmp_path):
    app = QApplication.instance() or QApplication([])
    assert app is not None
    window = PlatformWindow(PlatformStore(tmp_path / 'state.db', 'tester'))
    calls = []
    window.send.clicked.disconnect()
    window.send.clicked.connect(lambda: calls.append(True))
    try:
        QApplication.sendEvent(window.composer, QInputMethodEvent('shenhe', []))
        QTest.keyClick(window.composer, Qt.Key.Key_Return)
        assert not calls
        commit = QInputMethodEvent()
        commit.setCommitString('审核')
        QApplication.sendEvent(window.composer, commit)
        repeat = QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Return,
                           Qt.KeyboardModifier.NoModifier, '\r', True)
        QApplication.sendEvent(window.composer, repeat)
        assert not calls
        QTest.keyClick(window.composer, Qt.Key.Key_Return)
        assert calls == [True]
        assert window.composer.toPlainText() == '审核'
    finally:
        window.close()
