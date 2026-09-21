import os
import subprocess
import sys


def test_native_action_prompt_receipt_and_cancellation(tmp_path):
    code = r'''
import sys
from pathlib import Path
from PySide6.QtCore import QTimer
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import QApplication
from test_browser_action_gate import connected
from asset_based_agent.technical_platform.browser_action_prompt import BrowserActionPrompt
app = QApplication([])
font_id = QFontDatabase.addApplicationFont('C:/Windows/Fonts/msyh.ttc')
assert font_id >= 0
app.setFont(QFont(QFontDatabase.applicationFontFamilies(font_id)[0], 10))
root = Path(sys.argv[1])
for scenario in ('accept', 'decline', 'close', 'invalid', 'full'):
    active = [True]
    prompt = BrowserActionPrompt(is_active=lambda _: active[0],
                                 permission_mode=lambda: 'full' if scenario == 'full' else 'request')
    case = root / scenario; case.mkdir()
    store, observer, leases, lease, page, observation, _ = connected(case, prompt)
    def act():
        dialog = prompt.dialog
        assert dialog is not None
        assert not dialog.allow_button.isEnabled()
        assert dialog.cancel_button.isDefault()
        assert '<b>literal</b>' in dialog.details.toPlainText()
        assert 'https://example.com' in dialog.details.toPlainText()
        if scenario == 'accept':
            dialog.consent.setChecked(True)
            assert dialog.allow_button.isEnabled()
            dialog.grab().save(str(case / 'confirmation.png'))
            dialog.allow_button.click()
        elif scenario == 'decline': dialog.cancel_button.click()
        elif scenario == 'close': prompt.close()
        else: active[0] = False
    if scenario != 'full': QTimer.singleShot(40, act)
    QTimer.singleShot(2000, prompt.close)
    before = len(page.calls); results = []
    observer.edit(lease, observation, '1', 'fill', '<b>literal</b>', callback=results.append)
    with store.connect() as db:
        rows = db.execute('SELECT consumed FROM browser_action_authorizations').fetchall()
    if scenario in ('accept', 'full'):
        assert [row[0] for row in rows] == [1]
        page.calls[-1][2]('{"status":"dispatched"}')
        assert results == ['dispatched']
        if scenario == 'full': assert prompt.dialog is None
    else:
        assert not rows and results == ['rejected'] and len(page.calls) == before
    prompt.close()
print('native browser confirmation: ok')
'''
    env = dict(os.environ, QT_QPA_PLATFORM='offscreen')
    env['PYTHONPATH'] = os.pathsep.join(['src', 'tests/technical_platform', env.get('PYTHONPATH', '')])
    result = subprocess.run([sys.executable, '-X', 'utf8', '-c', code, str(tmp_path)],
                            env=env, capture_output=True, text=True, encoding='utf-8', timeout=35, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
