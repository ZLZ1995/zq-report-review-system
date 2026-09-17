import importlib.util
from pathlib import Path


def test_product_regression_includes_update_security_suite():
    root = Path(__file__).resolve().parents[2]
    spec = importlib.util.spec_from_file_location(
        'product_regression', root / 'scripts/test_report_review_productization.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert root / 'tests/platform_update' in module.SUITES


def test_release_export_includes_update_tests_and_public_signing_tools_only():
    root = Path(__file__).resolve().parents[2]
    spec = importlib.util.spec_from_file_location('release_export', root / 'scripts/export_client_release.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    selected = module.collect_paths(root)
    assert root / 'tests/platform_update/test_manifest.py' in selected
    assert root / 'scripts/create_release_signing_key.py' in selected
    assert root / 'scripts/sign_client_release.py' in selected
    assert root / 'scripts/run_client_updater.py' in selected
    assert root / 'scripts/run_client_launcher.py' in selected
    assert all(path.is_relative_to(root) and path.name != 'KEY' for path in selected)

