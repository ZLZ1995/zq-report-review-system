import os

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QDialogButtonBox


def test_upload_prompt_requires_explicit_consent_and_live_context(tmp_path):
    from asset_based_agent.technical_platform.browser_upload_prompt import UploadDialog
    app = QApplication.instance() or QApplication([])
    QFontDatabase.addApplicationFont('C:/Windows/Fonts/msyh.ttc')
    app.setFont(QFont('Microsoft YaHei', 10))
    artifact = {'id':'a','name':'合成审核报告.docx','size':1024,'sha256':'a'*64}
    active = [True]
    dialog = UploadDialog(None, 'https://example.com', '测试项目001 <b>不得按HTML显示</b>',
                          '附件上传', artifact, lambda: active[0])
    dialog.show(); QTest.qWait(30)
    ok = dialog.buttons.button(QDialogButtonBox.StandardButton.Ok)
    assert not ok.isEnabled()
    assert '<b>' in dialog.details.toPlainText()
    dialog.grab().save(str(tmp_path / 'upload-confirmation.png'))
    dialog.consent.setChecked(True)
    assert ok.isEnabled()
    QTest.mouseClick(ok, Qt.MouseButton.LeftButton)
    assert dialog.result() == QDialog.DialogCode.Accepted
    dialog.deleteLater()
    dialog = UploadDialog(None, 'https://example.com', '测试项目001', '附件上传', artifact, lambda: active[0])
    dialog.show(); dialog.consent.setChecked(True)
    active[0] = False
    QTest.qWait(150)
    assert not dialog.isVisible() and dialog.result() == QDialog.DialogCode.Rejected
    dialog.deleteLater()


def test_oa_upload_requires_acknowledging_current_version_effect():
    from asset_based_agent.technical_platform.browser_upload_prompt import UploadDialog
    app = QApplication.instance() or QApplication([])
    artifact = {'id': 'a', 'name': 'synthetic.docx', 'size': 1, 'sha256': 'a' * 64}
    dialog = UploadDialog(None, 'https://zhongqinoa01.com', 'Project 20',
                          '上传待审报告包', artifact, lambda: True)
    try:
        dialog.consent.setChecked(True)
        assert not dialog.buttons.button(QDialogButtonBox.StandardButton.Ok).isEnabled()
        assert '替换' in dialog.details.toPlainText()
        dialog.effect_consent.setChecked(True)
        assert dialog.buttons.button(QDialogButtonBox.StandardButton.Ok).isEnabled()
    finally:
        dialog.close()
        dialog.deleteLater()
        app.processEvents()
