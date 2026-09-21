import importlib.util
from pathlib import Path

import pytest


def test_login_smoke_requires_the_explicit_candidate_resources(tmp_path):
    script = Path(__file__).resolve().parents[2] / 'scripts/smoke_technical_platform_exe.py'
    spec = importlib.util.spec_from_file_location('candidate_login_smoke', script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with pytest.raises(FileNotFoundError):
        module.main(tmp_path)

