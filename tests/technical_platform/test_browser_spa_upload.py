import os
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.parametrize('case', ['normal', 'hidden_wrapper', 'ambiguous', 'disabled',
                                 'cross_origin', 'explicit_get', 'submit_button', 'mutated'])
def test_spa_upload_requires_visible_unique_binding_and_revalidates(tmp_path, case):
    probe = Path(__file__).parent / 'probes' / 'spa_upload.py'
    result = subprocess.run([sys.executable, '-X', 'utf8', str(probe), str(tmp_path), case],
        env=dict(os.environ, QT_QPA_PLATFORM='offscreen'), capture_output=True,
        text=True, encoding='utf-8', timeout=40, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'spa-upload-component: passed' in result.stdout
