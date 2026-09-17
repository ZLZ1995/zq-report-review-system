from pathlib import Path


def test_server_dockerfile_copies_shared_agent_package():
    dockerfile = (
        Path(__file__).resolve().parents[2]
        / 'deploy'
        / 'report_review_server'
        / 'Dockerfile'
    ).read_text(encoding='utf-8')
    assert 'COPY src/asset_based_agent /app/src/asset_based_agent' in dockerfile
