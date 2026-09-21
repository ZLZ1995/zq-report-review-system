import os
import subprocess
import sys
from pathlib import Path


def test_native_upload_worker_receipt_and_real_page_dispatch_once(tmp_path):
    probe = Path(__file__).parent / 'probes' / 'native_upload_webengine.py'
    result = subprocess.run([sys.executable, '-X', 'utf8', str(probe), str(tmp_path)],
        env=dict(os.environ, QT_QPA_PLATFORM='offscreen'), capture_output=True,
        text=True, encoding='utf-8', timeout=60, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
    assert '"status": "passed"' in result.stdout
