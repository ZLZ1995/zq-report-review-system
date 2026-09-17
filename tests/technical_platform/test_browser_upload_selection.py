import os
import time

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QDialogButtonBox
from test_browser_upload_source import source


def test_selection_requires_user_choice_and_rejects_stale_context(tmp_path):
    from asset_based_agent.technical_platform.browser_upload_selection import (
        UploadSelectionDialog,
    )
    app = QApplication.instance() or QApplication([])
    assert app is not None
    QFontDatabase.addApplicationFont('C:/Windows/Fonts/msyh.ttc')
    app.setFont(QFont('Microsoft YaHei', 10))
    store, session, *_ = source(tmp_path)
    active = [True]
    dialog = UploadSelectionDialog(None, store, session, lambda: active[0])
    dialog.show()
    deadline = time.monotonic() + 10
    while dialog.worker.isRunning() or not dialog.loaded:
        assert time.monotonic() < deadline
        QTest.qWait(10)
    assert dialog.files.count() == 1
    dialog.grab().save(str(tmp_path / 'upload-selection.png'))
    ok = dialog.buttons.button(QDialogButtonBox.StandardButton.Ok)
    assert not ok.isEnabled() and dialog.selected == []
    dialog.files.item(0).setCheckState(Qt.CheckState.Checked)
    assert ok.isEnabled()
    dialog.accept()
    assert dialog.result() == QDialog.DialogCode.Accepted
    assert len(dialog.selected) == 1 and 'path' not in repr(dialog.selected)
    dialog.deleteLater()
    dialog = UploadSelectionDialog(None, store, session, lambda: active[0])
    dialog.show(); active[0] = False
    deadline = time.monotonic() + 10
    while dialog.isVisible():
        assert time.monotonic() < deadline
        QTest.qWait(10)
    assert not dialog.worker.isRunning() and dialog.selected == []
    dialog.deleteLater()
