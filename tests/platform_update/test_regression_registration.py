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
    assert root / 'scripts/verify_client_release.py' in selected
    assert root / 'scripts/run_client_updater.py' in selected
    assert root / 'scripts/run_client_launcher.py' in selected
    assert all(path.is_relative_to(root) and path.name != 'KEY' for path in selected)


def test_release_checkout_has_fail_closed_container_ignore_rules():
    root = Path(__file__).resolve().parents[2]
    rules = (root / '.dockerignore').read_text(encoding='utf-8').splitlines()
    for entry in ('.git', '.venv*', 'dist', 'outputs', 'runs', 'credentials',
                  'browser_profiles', '.env*', 'KEY', '*.pem', '*.key'):
        assert entry in rules


def test_ci_builds_client_and_server_and_runs_static_security_gates():
    root = Path(__file__).resolve().parents[2]
    client = (root / '.github/workflows/client-ci.yml').read_text(
        encoding='utf-8').replace('\\', '/')
    server = (root / '.github/workflows/server-ci.yml').read_text(encoding='utf-8')
    assert 'scripts/build_technical_platform.py' in client
    assert 'scripts/package_technical_platform.py' in client
    assert 'actions/upload-artifact@v4' in client
    assert 'ruff check' in client
    assert 'tests/platform_update' in client
    assert 'ruff check' in server
    assert 'tests/report_review_server' in server
    assert 'docker build' in server


def test_release_asset_workflow_only_promotes_an_exact_successful_ci_artifact():
    root = Path(__file__).resolve().parents[2]
    workflow = (root / '.github/workflows/release-assets.yml').read_text(
        encoding='utf-8')
    assert 'workflow_dispatch:' in workflow
    assert 'permissions:\n  actions: read\n  contents: write' in workflow
    assert 'gh run download "$SOURCE_RUN_ID"' in workflow
    assert 'zq-workspace-windows-$SOURCE_SHA' in workflow
    assert '[[ "$SOURCE_SHA" =~ ^[0-9a-f]{40}$ ]]' in workflow
    assert 'gh release view "$RELEASE_TAG"' in workflow
    assert "grep -qx true" in workflow
    assert 'VERSION="${RELEASE_TAG#v}"' in workflow
    assert 'ZQ-Workspace-$VERSION-Windows.zip' in workflow
    assert 'ZQ-Workspace-$VERSION-Managed-Windows.zip' in workflow
    assert 'ZQ-Workspace-0.2.7-Windows.zip' not in workflow
    assert '--clobber' in workflow
