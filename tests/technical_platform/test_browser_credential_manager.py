import os
import subprocess
import sys


def test_browser_credentials_manager_consent_and_close(tmp_path):
    code = r'''
import sys
from pathlib import Path
from PySide6.QtWidgets import QApplication, QLabel
from asset_based_agent.technical_platform.storage_preferences import StoragePreferences
from asset_based_agent.technical_platform.browser_profile import BrowserSession
from asset_based_agent.technical_platform.browser_panel import BrowserPanel
from asset_based_agent.technical_platform.browser_credential_vault import CredentialVault
root=Path(sys.argv[1])
(root/'program').mkdir(); (root/'data').mkdir()
prefs=StoragePreferences(root/'index.sqlite', root/'program')
prefs.select('alice',root/'data')
vault=CredentialVault(prefs,'alice',environment='test')
key=vault.save('https://example.com','test-user','synthetic-password',confirmed=True,login_succeeded=True)
app=QApplication([])
with BrowserSession(prefs,'alice',environment='test') as session:
    panel=BrowserPanel(session)
    panel.show(); panel.open_credentials()
    manager=panel.credentials_dialog
    assert manager.accounts.count()==1
    assert 'test-user' in manager.accounts.item(0).text()
    assert not manager.delete_button.isEnabled()
    manager.accounts.setCurrentRow(0)
    assert manager.delete_button.isEnabled()
    assert manager.agent_button.isEnabled()
    manager.confirm=lambda message: False
    manager.agent_button.click()
    assert not vault.agent_accounts('https://example.com')
    manager.delete_button.click()
    assert vault.entries()[0].key==key
    manager.confirm=lambda message: True
    manager.agent_button.click()
    assert vault.agent_accounts('https://example.com')[0].key==key
    manager.accounts.setCurrentRow(0)
    assert '撤销' in manager.agent_button.text()
    manager.agent_button.click()
    assert not vault.agent_accounts('https://example.com')
    manager.accounts.setCurrentRow(0)
    manager.never_button.click()
    assert vault.prompt_policy('https://example.com')=='never'
    assert manager.blocked.count()==1
    manager.blocked.setCurrentRow(0)
    manager.restore_button.click()
    assert vault.prompt_policy('https://example.com')=='ask'
    manager.accounts.setCurrentRow(0)
    app.processEvents()
    manager.grab().save(str(root/'credential-manager.png'))
    assert all('synthetic-password' not in label.text() for label in manager.findChildren(QLabel))
    manager.delete_button.click()
    assert not vault.entries()
    key=vault.save('https://example.com','test-user','synthetic-password',confirmed=True,login_succeeded=True)
    manager.refresh(); manager.accounts.setCurrentRow(0)
    from PySide6.QtCore import QTimer
    manager2=type(manager)(vault)
    manager2.refresh(); manager2.accounts.setCurrentRow(0)
    QTimer.singleShot(20, manager2.shutdown)
    manager2.agent_button.click()
    assert manager2._closed and not vault.agent_accounts('https://example.com')
    manager.confirm=type(manager).confirm.__get__(manager)
    QTimer.singleShot(20, manager.shutdown)
    manager.delete_button.click()
    assert manager._closed
    assert not vault.agent_accounts('https://example.com')
    assert vault.entries()[0].key==key
    panel.shutdown(); panel.close()
print('credential-manager: ok')
'''
    result = subprocess.run([sys.executable, '-X', 'utf8', '-c', code, str(tmp_path)],
                            env=os.environ.copy(), capture_output=True, text=True,
                            timeout=60, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'credential-manager: ok' in result.stdout
