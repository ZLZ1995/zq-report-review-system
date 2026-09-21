import importlib.util
import json
import zipfile
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


def test_packaging_emits_managed_transition_bundle_without_user_data(tmp_path):
    script = Path(__file__).resolve().parents[2] / 'scripts/package_technical_platform.py'
    spec = importlib.util.spec_from_file_location('package_managed_test', script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    client = tmp_path / 'ZQ技术平台'
    rules = client / '_internal/asset_based_agent/technical_platform/review_rules.txt'
    rules.parent.mkdir(parents=True)
    source_rules = tmp_path / 'src/asset_based_agent/technical_platform/review_rules.txt'
    source_rules.parent.mkdir(parents=True)
    source_rules.write_bytes(b'rules')
    rules.write_bytes(b'rules')
    (client / 'ZQ技术平台.exe').write_bytes(b'client')
    helper = client / '_internal/PySide6/QtWebEngineProcess.exe'
    helper.parent.mkdir(parents=True)
    helper.write_bytes(b'webengine-helper')
    for skill in ('valuation-detail-workbook-fill', 'gongshang-change-history-docx',
                  'financial-brief-docx'):
        source = tmp_path / 'assets/builtin_templates' / skill
        source.mkdir(parents=True)
        (source / 'template.xlsx').write_bytes(b'template')
        bundle = client / '_internal/builtin_skills' / skill
        bundle.mkdir(parents=True)
        (bundle / 'template.xlsx').write_bytes(b'template')
        (bundle / 'template.lock.json').write_text(json.dumps({
            'path': 'template.xlsx',
            'sha256': __import__('hashlib').sha256(b'template').hexdigest(),
        }), encoding='utf-8')
    bootstrap = tmp_path / 'bootstrap'
    bootstrap.mkdir()
    (bootstrap / 'ZQ技术平台更新器.exe').write_bytes(b'updater')
    (bootstrap / 'ZQ技术平台启动器.exe').write_bytes(b'launcher')

    module.main(tmp_path)

    managed = tmp_path / f'ZQ-Workspace-{module.CLIENT_VERSION}-Managed-Windows.zip'
    assert managed.is_file()
    with zipfile.ZipFile(managed) as archive:
        names = set(archive.namelist())
        assert 'ZQ技术平台启动器.exe' in names
        assert 'ZQ技术平台更新器.exe' in names
        assert 'installation-policy.json' in names
        assert 'update-state.sqlite' in names
        assert 'installation-lock.sqlite' in names
        assert f'versions/{module.CLIENT_VERSION}/ZQ技术平台/ZQ技术平台.exe' in names
        assert (f'versions/{module.CLIENT_VERSION}/ZQ技术平台/_internal/PySide6/'
                'QtWebEngineProcess.pending') in names
        assert not any(name.endswith('/PySide6/QtWebEngineProcess.exe') for name in names)
        assert not any('/runs/' in name or '/credentials/' in name for name in names)

    ordinary = tmp_path / f'ZQ-Workspace-{module.CLIENT_VERSION}-Windows.zip'
    with zipfile.ZipFile(ordinary) as archive:
        names = set(archive.namelist())
        assert 'ZQ技术平台/_internal/PySide6/QtWebEngineProcess.pending' in names
        assert 'ZQ技术平台/_internal/PySide6/QtWebEngineProcess.exe' not in names
