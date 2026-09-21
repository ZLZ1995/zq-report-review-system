import os
import subprocess
import sys

import pytest


@pytest.mark.parametrize('exception', [True, False])
def test_unhandled_exception_with_live_browser_keeps_python_exit_code(tmp_path, exception):
    code = r'''
import sys
from pathlib import Path
from PySide6.QtWidgets import QApplication
from asset_based_agent.technical_platform.storage_preferences import StoragePreferences
from asset_based_agent.technical_platform.browser_profile import BrowserSession
from asset_based_agent.technical_platform.browser_panel import BrowserPanel
root = Path(sys.argv[1])
program, data = root/'program', root/'data'
program.mkdir(); data.mkdir()
prefs = StoragePreferences(root/'index.sqlite', program)
prefs.select('synthetic', data)
app = QApplication([])
session = BrowserSession(prefs, 'synthetic', environment='test')
session.__enter__()
panel = BrowserPanel(session)
panel.show()
app.processEvents()
raise RuntimeError('synthetic-exit-probe')
'''
    if not exception:
        code = code.replace("raise RuntimeError('synthetic-exit-probe')", 'sys.exit(0)')
    result = subprocess.run([sys.executable, '-X', 'utf8', '-c', code, str(tmp_path)],
                            env=os.environ.copy(), capture_output=True, text=True,
                            timeout=60, check=False)
    assert result.returncode == (1 if exception else 0), (result.returncode, result.stdout, result.stderr)
    if exception:
        assert 'synthetic-exit-probe' in result.stderr
