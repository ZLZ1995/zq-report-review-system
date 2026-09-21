"""Public compatibility metadata must not claim unimplemented behavior."""


def test_capabilities_are_public_versioned_and_only_advertise_present_routes(client):
    response = client.get('/api/v1/capabilities')
    assert response.status_code == 200
    data = response.json()
    assert data['schema_version'] == 1
    assert data['protocol_version'] == 1
    assert data['build_sha'] is None
    assert data['capabilities']['skill_routing'] == 1
    assert data['capabilities']['review_events'] == 1
    assert data['capabilities']['agent_completion_stream'] == 1
    assert 'browser_automation' not in data['capabilities']
    assert 'agent_understanding' not in data['capabilities']
    assert set(data) == {'schema_version', 'protocol_version', 'build_sha', 'capabilities'}


def test_build_identity_is_explicit_and_validated(monkeypatch):
    import pytest

    from asset_based_agent.report_review_server.config import ServerSettings
    monkeypatch.setenv('REPORT_REVIEW_BUILD_SHA', 'a' * 40)
    assert ServerSettings.from_environment().build_sha == 'a' * 40
    monkeypatch.setenv('REPORT_REVIEW_BUILD_SHA', 'secret or arbitrary text')
    with pytest.raises(ValueError, match='BUILD_SHA'):
        ServerSettings.from_environment()


def test_immutable_image_build_identity_overrides_stale_runtime_value(monkeypatch):
    from asset_based_agent.report_review_server.config import ServerSettings

    monkeypatch.setenv('REPORT_REVIEW_BUILD_SHA', 'a' * 40)
    monkeypatch.setenv('REPORT_REVIEW_IMAGE_BUILD_SHA', 'b' * 40)
    assert ServerSettings.from_environment().build_sha == 'b' * 40
