import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest


@pytest.mark.skipif(os.name != 'nt', reason='Windows DPAPI offline signer')
def test_offline_signer_reads_protected_key_without_printing_private_material(tmp_path):
    root = Path(__file__).resolve().parents[2]
    key_path = tmp_path / 'KEY'
    result = subprocess.run([sys.executable, str(root / 'scripts/create_release_signing_key.py'),
                             '--key-path', str(key_path), '--key-id', 'synthetic-cli'],
                            capture_output=True, text=True, check=True)
    assert json.loads(result.stdout)['key_id'] == 'synthetic-cli'
    package = tmp_path / 'synthetic.zip'
    package.write_bytes(b'synthetic bytes, never published')
    now = int(time.time())
    metadata = {'schema_version': 1, 'key_id': 'synthetic-cli', 'sequence': 10, 'version': '0.2.7',
                'platform': 'windows', 'arch': 'x86_64', 'url': 'https://releases.test/app.zip',
                'protocol_min': 1, 'protocol_max': 1, 'data_schema_min': 1, 'data_schema_max': 30,
                'minimum_updater': '1.0.0', 'issued_at': now - 10, 'expires_at': now + 600, 'notes': 'test'}
    policy = {'current_version': '0.2.6', 'last_sequence': 9, 'platform': 'windows', 'arch': 'x86_64',
              'protocol': 1, 'data_schema': 10, 'updater_version': '1.0.0', 'allowed_hosts': ['releases.test']}
    metadata_path, policy_path = tmp_path / 'metadata.json', tmp_path / 'policy.json'
    metadata_path.write_text(json.dumps(metadata), encoding='utf8')
    policy_path.write_text(json.dumps(policy), encoding='utf8')
    output = tmp_path / 'signed.json'
    command = [sys.executable, str(root / 'scripts/sign_client_release.py'),
               '--key-path', str(key_path), '--package', str(package),
               '--metadata', str(metadata_path), '--policy', str(policy_path), '--output', str(output)]
    signed = subprocess.run(command, capture_output=True, text=True, check=False)
    assert signed.returncode == 0, signed.stderr
    assert json.loads(signed.stdout)['key_id'] == 'synthetic-cli'
    assert 'ciphertext' not in signed.stdout
    assert json.loads(output.read_bytes())['signature']
    repeat = subprocess.run(command, capture_output=True, text=True, check=False)
    assert repeat.returncode != 0
    assert 'ciphertext' not in repeat.stdout + repeat.stderr

