import json
import subprocess
import sys
from pathlib import Path


def test_independent_updater_bootstrap_is_explicit_and_immutable(tmp_path):
    root = Path(__file__).resolve().parents[2]
    installation = tmp_path / 'installation'
    baseline = installation / 'versions/0.2.6/ZQ����ƽ̨'
    baseline.mkdir(parents=True)
    (baseline / 'ZQ����ƽ̨.exe').write_bytes(b'synthetic baseline - not executable')
    policy = tmp_path / 'policy.json'
    policy.write_text(json.dumps({'current_version': '0.2.6', 'last_sequence': 9,
                                  'platform': 'windows', 'arch': 'x86_64', 'protocol': 1,
                                  'data_schema': 10, 'updater_version': '1.0.0',
                                  'allowed_hosts': ['releases.test']}), encoding='utf8')
    command = [sys.executable, str(root / 'scripts/run_client_updater.py'), 'initialize',
               '--installation-root', str(installation), '--policy', str(policy)]
    result = subprocess.run(command, capture_output=True, timeout=30, check=False)
    assert result.returncode == 0, result.stderr.decode(errors='replace')
    assert (installation / 'update-state.sqlite').is_file()
    previous = (installation / 'update-state.sqlite').read_bytes()
    again = subprocess.run(command, capture_output=True, timeout=30, check=False)
    assert again.returncode != 0
    assert (installation / 'update-state.sqlite').read_bytes() == previous

