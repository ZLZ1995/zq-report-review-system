"""Baseline inventories must not inspect user documents or credential values."""
import importlib.util
from pathlib import Path


def test_baseline_hashes_only_declared_release_inputs(tmp_path):
    script = Path(__file__).resolve().parents[2] / 'scripts/check_agent_release_baseline.py'
    spec = importlib.util.spec_from_file_location('release_baseline_probe', script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    template = tmp_path / 'assets/builtin_templates/example/template.xlsx'
    template.parent.mkdir(parents=True)
    template.write_bytes(b'locked-template')
    user = tmp_path / 'inputs/customer-secret.docx'
    user.parent.mkdir()
    user.write_bytes(b'NEVER_INSPECT_OR_PUBLISH')
    report = module.release_inventory(tmp_path)
    assert len(report) == 1
    assert report[0]['path'] == 'assets/builtin_templates/example/template.xlsx'
    assert len(report[0]['sha256']) == 64
    assert 'NEVER' not in str(report)
    assert 'customer-secret' not in str(report)
