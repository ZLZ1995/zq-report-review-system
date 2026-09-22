import hashlib
import importlib.util
import json
import zipfile
from pathlib import Path

import pytest


PLATFORM_DIR = 'ZQ\u6280\u672f\u5e73\u53f0'
UPDATER = f'{PLATFORM_DIR}\u66f4\u65b0\u5668.exe'
LAUNCHER = f'{PLATFORM_DIR}\u542f\u52a8\u5668.exe'


def load_script():
    script = Path(__file__).resolve().parents[2] / 'scripts/package_technical_platform.py'
    spec = importlib.util.spec_from_file_location('package_candidate_test', script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def prepare_tree(root, source_root=None):
    source_root = source_root or root
    source_rules = source_root / 'src/asset_based_agent/technical_platform/review_rules.txt'
    source_rules.parent.mkdir(parents=True, exist_ok=True)
    source_rules.write_bytes(b'rules')
    client = root / PLATFORM_DIR
    rules = client / '_internal/asset_based_agent/technical_platform/review_rules.txt'
    rules.parent.mkdir(parents=True)
    rules.write_bytes(b'rules')
    (client / f'{PLATFORM_DIR}.exe').write_bytes(b'client')
    helper = client / '_internal/PySide6/QtWebEngineProcess.exe'
    helper.parent.mkdir(parents=True)
    helper.write_bytes(b'webengine-helper')
    for skill in ('valuation-detail-workbook-fill', 'gongshang-change-history-docx',
                  'financial-brief-docx'):
        bundle = client / '_internal/builtin_skills' / skill
        bundle.mkdir(parents=True)
        (bundle / 'template.xlsx').write_bytes(b'template')
        (bundle / 'template.lock.json').write_text(json.dumps({
            'path': 'template.xlsx',
            'sha256': hashlib.sha256(b'template').hexdigest(),
        }), encoding='utf-8')
    bootstrap = root / 'bootstrap'
    bootstrap.mkdir(parents=True)
    (bootstrap / UPDATER).write_bytes(b'updater')
    (bootstrap / LAUNCHER).write_bytes(b'launcher')


def test_existing_package_is_never_overwritten(tmp_path):
    module = load_script()
    package = tmp_path / f'ZQ-Workspace-{module.CLIENT_VERSION}-Windows.zip'
    package.write_bytes(b'previous verified distribution')
    with pytest.raises(FileExistsError):
        module.main(tmp_path)
    assert package.read_bytes() == b'previous verified distribution'


def test_missing_client_cannot_produce_empty_release(tmp_path):
    module = load_script()
    with pytest.raises(FileNotFoundError):
        module.main(tmp_path)
    assert not list(tmp_path.glob('*.zip'))


def test_packaging_emits_managed_transition_bundle_without_user_data(tmp_path):
    module = load_script()
    prepare_tree(tmp_path)
    module.main(tmp_path)
    managed = tmp_path / f'ZQ-Workspace-{module.CLIENT_VERSION}-Managed-Windows.zip'
    ordinary = tmp_path / f'ZQ-Workspace-{module.CLIENT_VERSION}-Windows.zip'
    assert managed.is_file() and ordinary.is_file()
    with zipfile.ZipFile(managed) as archive:
        names = set(archive.namelist())
        assert UPDATER in names and LAUNCHER in names
        assert 'installation-policy.json' in names
        assert f'versions/{module.CLIENT_VERSION}/{PLATFORM_DIR}/{PLATFORM_DIR}.exe' in names
        assert any(name.endswith('/PySide6/QtWebEngineProcess.pending') for name in names)
        assert not any('/runs/' in name or '/credentials/' in name for name in names)
    with zipfile.ZipFile(ordinary) as archive:
        names = set(archive.namelist())
        assert any(name.endswith('/PySide6/QtWebEngineProcess.pending') for name in names)
        assert not any(name.endswith('/PySide6/QtWebEngineProcess.exe') for name in names)


def test_packaging_accepts_build_root_separate_from_source_root(tmp_path):
    module = load_script()
    source_root = tmp_path / 'source'
    package_root = tmp_path / 'build'
    prepare_tree(package_root, source_root)
    module.main(package_root, source_root=source_root)
    assert (package_root / f'ZQ-Workspace-{module.CLIENT_VERSION}-Windows.zip').is_file()
