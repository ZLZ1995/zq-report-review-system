from pathlib import Path


def test_server_dockerfile_copies_shared_agent_package():
    dockerfile = (
        Path(__file__).resolve().parents[2]
        / 'deploy'
        / 'report_review_server'
        / 'Dockerfile'
    ).read_text(encoding='utf-8')
    assert 'COPY src/asset_based_agent /app/src/asset_based_agent' in dockerfile


def test_repository_root_has_server_build_fallback():
    root_dockerfile = Path(__file__).resolve().parents[2] / 'Dockerfile'
    assert root_dockerfile.is_file()
    assert 'COPY src/asset_based_agent /app/src/asset_based_agent' in root_dockerfile.read_text(encoding='utf-8')


def test_legacy_server_context_contains_contract_compatibility_modules():
    root = Path(__file__).resolve().parents[2] / 'src' / 'asset_based_agent' / 'report_review_server'
    assert (root / 'compat_agent_contracts.py').is_file()
    assert (root / 'compat_browser_contracts.py').is_file()
    assert 'legacy Zeabur build context' in (root / 'api.py').read_text(encoding='utf-8')
