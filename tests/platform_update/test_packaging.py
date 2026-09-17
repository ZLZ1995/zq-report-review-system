import importlib.util
from pathlib import Path

import pytest


def test_existing_package_is_never_overwritten(tmp_path):
    script = Path(__file__).resolve().parents[2] / 'scripts/package_technical_platform.py'
    spec = importlib.util.spec_from_file_location('package_candidate_test', script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    package = tmp_path / f'ZQ-Workspace-{module.CLIENT_VERSION}-Windows.zip'
    package.write_bytes(b'previous verified distribution')
    with pytest.raises(FileExistsError):
        module.main(tmp_path)
    assert package.read_bytes() == b'previous verified distribution'


def test_missing_client_cannot_produce_empty_release(tmp_path):
    script = Path(__file__).resolve().parents[2] / 'scripts/package_technical_platform.py'
    spec = importlib.util.spec_from_file_location('package_missing_test', script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with pytest.raises(FileNotFoundError):
        module.main(tmp_path)
    assert not list(tmp_path.glob('*.zip'))

