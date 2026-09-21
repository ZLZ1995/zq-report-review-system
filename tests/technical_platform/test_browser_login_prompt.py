import os
import subprocess
import sys


def test_account_prompt_requires_choice_and_aborts_on_context_change(tmp_path):
    code = r'''
import sys
from pathlib import Path
from PySide6.QtCore import QTimer
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import QApplication, QDialogButtonBox
from asset_based_agent.technical_platform.browser_credential_vault import AgentAccount
from asset_based_agent.technical_platform.browser_login_prompt import LoginAccountDialog, select_login_account
app=QApplication([])
font=QFontDatabase.addApplicationFont('C:/Windows/Fonts/msyh.ttc')
app.setFont(QFont(QFontDatabase.applicationFontFamilies(font)[0],10))
accounts=[AgentAccount('one','https://example.com','a***'),AgentAccount('two','https://example.com','b***')]
for scenario in ('accept','cancel','stale'):
    active=[True]
    def interact():
        dialog=next(w for w in app.topLevelWidgets() if isinstance(w,LoginAccountDialog) and w.isVisible())
        assert not dialog.buttons.button(QDialogButtonBox.Ok).isEnabled()
        assert dialog.buttons.button(QDialogButtonBox.Cancel).isDefault()
        dialog.accounts.setCurrentIndex(2)
        assert dialog.buttons.button(QDialogButtonBox.Ok).isEnabled()
        if scenario=='accept':
            dialog.grab().save(str(Path(sys.argv[1])/'login-prompt.png'))
            dialog.accept()
        elif scenario=='cancel': dialog.reject()
        else: active[0]=False
    QTimer.singleShot(100,interact)
    selected=select_login_account(None,'https://example.com',accounts,lambda:active[0])
    assert selected==('two' if scenario=='accept' else None)
assert select_login_account(None,'https://example.com',accounts,lambda:False) is None
'''
    env = dict(os.environ, QT_QPA_PLATFORM='offscreen')
    env['PYTHONPATH'] = os.pathsep.join(['src', env.get('PYTHONPATH', '')])
    result = subprocess.run([sys.executable, '-X', 'utf8', '-c', code, str(tmp_path)],
                            env=env, capture_output=True, text=True, encoding='utf-8', timeout=20, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
