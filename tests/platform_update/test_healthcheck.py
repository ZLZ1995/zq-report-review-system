import json
import subprocess
import sys
from pathlib import Path

from asset_based_agent.technical_platform.release_info import CLIENT_VERSION


def test_launch_script_has_noninteractive_update_health_mode(tmp_path):
    root = Path(__file__).resolve().parents[2]
    request = tmp_path / 'request.json'
    output = tmp_path / 'health.json'
    request.write_text(json.dumps({'schema_version': 1, 'nonce': 'a' * 64,
                                  'response_path': str(output)}), encoding='utf8')
    command = [sys.executable, str(root / 'scripts/run_technical_platform.py'),
               '--update-healthcheck', str(request)]
    run = subprocess.run(command, capture_output=True, timeout=30, check=False)
    assert run.returncode == 0, run.stderr.decode(errors='replace')
    response = json.loads(output.read_bytes())
    assert response['nonce'] == 'a' * 64
    assert response['client_version'] == CLIENT_VERSION
    assert response['protocol_version'] == 1
    assert response['webengine_import'] is True
    assert all(s['status'] in ('verified', 'builtin') for s in response['skills'])
    original = output.read_bytes()
    repeat = subprocess.run(command, capture_output=True, timeout=30, check=False)
    assert repeat.returncode != 0
    assert output.read_bytes() == original

