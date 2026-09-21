import importlib.util
import json
import os
from pathlib import Path

import pytest


@pytest.mark.skipif(os.name != 'nt', reason='Windows DPAPI key custody')
def test_key_generation_is_encrypted_recoverable_and_never_overwrites(tmp_path):
    script = Path(__file__).resolve().parents[2] / 'scripts/create_release_signing_key.py'
    spec = importlib.util.spec_from_file_location('key_creator', script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    target = tmp_path / 'KEY'
    record = module.create_key(target, 'synthetic-test')
    original = target.read_bytes()
    stored = json.loads(original)
    assert stored['protection'] == 'windows-current-user-dpapi'
    assert record['key_id'] == 'synthetic-test'
    assert 'private_key' not in record
    assert module.public_record(target) == record
    with pytest.raises(FileExistsError):
        module.create_key(target, 'different')
    assert target.read_bytes() == original

