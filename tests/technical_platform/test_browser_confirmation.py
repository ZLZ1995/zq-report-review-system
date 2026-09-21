import os
import subprocess
import sys


def test_browser_scope_and_navigation_native_confirmation(tmp_path):
    code = r'''
import json, sys
from pathlib import Path
from hashlib import sha256
from PySide6.QtCore import QTimer
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import QApplication
from test_browser_task_spec import make_browser_run
from test_browser_action_receipts import ready
from asset_based_agent.technical_platform.plan_confirmation import PlanConfirmationDialog, confirmation_text
from asset_based_agent.technical_platform.browser_action_prompt import BrowserActionPrompt
app=QApplication([])
font_id=QFontDatabase.addApplicationFont('C:/Windows/Fonts/msyh.ttc')
app.setFont(QFont(QFontDatabase.applicationFontFamilies(font_id)[0],10))
root=Path(sys.argv[1]); (root/'scope').mkdir(); (root/'action').mkdir()
store,run,_=make_browser_run(root/'scope')
snapshot=json.loads(store.run(run)['snapshot'])
text=confirmation_text(snapshot,root)
assert 'https://example.com' in text and '浏览网页' in text and '读取网页' in text
assert 'test' in text and '模型' in text and '上传' in text
dialog=PlanConfirmationDialog(snapshot,root)
assert not dialog.confirm_button.isEnabled()
assert dialog.cancel_button.isDefault()
dialog.consent.setChecked(True); assert dialog.confirm_button.isEnabled()
dialog.show(); app.processEvents(); dialog.grab().save(str(root/'scope.png')); dialog.close()
_,_,_,request=ready(root/'action')
url='https://example.com/project?id=123'
request=request.model_copy(update={'action':'navigate','payload_sha256':sha256(url.encode()).hexdigest()})
active=[True]; prompt=BrowserActionPrompt(is_active=lambda _:active[0])
assert prompt.navigate(request,'https://other.test/') is False
assert prompt.dialog is None
assert prompt.navigate(request,url+'4') is False
def accept():
    dialog=prompt.dialog
    assert dialog is not None and url in dialog.details.toPlainText()
    assert '浏览网页' in dialog.details.toPlainText()
    assert not dialog.allow_button.isEnabled() and dialog.cancel_button.isDefault()
    dialog.consent.setChecked(True)
    dialog.grab().save(str(root/'navigation.png'))
    dialog.allow_button.click()
QTimer.singleShot(40,accept)
QTimer.singleShot(2500,prompt.close)
assert prompt.navigate(request,url) is True
prompt.close()
print('browser confirmations: ok')
'''
    env = dict(os.environ, QT_QPA_PLATFORM='offscreen')
    env['PYTHONPATH'] = os.pathsep.join(['src', 'tests/technical_platform', env.get('PYTHONPATH', '')])
    result = subprocess.run([sys.executable, '-X', 'utf8', '-c', code, str(tmp_path)], env=env,
                            capture_output=True, text=True, encoding='utf-8', timeout=25, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
