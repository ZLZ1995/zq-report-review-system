import json

import pytest

from .conftest import bearer, login


def test_discover_then_select_and_save_without_precreated_model(client, monkeypatch):
    from asset_based_agent.report_review_server.services import model_discovery
    monkeypatch.setattr(model_discovery, "fetch_models", lambda url, key: ["deepseek-chat", "deepseek-reasoner"])
    headers = bearer(login(client, "admin", "AdminPassword123!", instance="discovery")["access_token"])
    credentials = {"base_url": "https://api.deepseek.com", "api_key": "test-secret"}
    result = client.post("/api/v1/admin/channels/discover", headers=headers, json=credentials)
    assert result.status_code == 200
    assert result.json()["models"] == ["deepseek-chat", "deepseek-reasoner"]
    assert "test-secret" not in result.text
    assert client.get("/api/v1/admin/overview", headers=headers).json()["models"] == []
    payload = {**credentials, "discovery_token": result.json()["discovery_token"],
               "provider_model": "deepseek-reasoner", "priority": 1,
               "rates": dict.fromkeys(["input", "output", "cache_hit", "cache_miss", "reasoning"], "1")}
    invalid = client.post("/api/v1/admin/channels", headers=headers, json={**payload, "provider_model": "invented"})
    assert invalid.status_code == 422
    assert client.post("/api/v1/admin/channels", headers=headers, json={**payload, "api_key": "changed"}).status_code == 422
    saved = client.post("/api/v1/admin/channels", headers=headers, json=payload)
    assert saved.status_code == 201
    overview = client.get("/api/v1/admin/overview", headers=headers).json()
    assert len(overview["models"]) == 1
    assert overview["routes"][0]["provider_model"] == "deepseek-reasoner"
    assert "test-secret" not in str(overview)


def test_discovery_requires_authentication(client):
    assert client.post("/api/v1/admin/channels/discover", json={"base_url": "https://api.deepseek.com", "api_key": "x"}).status_code == 401


def test_discovery_rejects_private_destinations(monkeypatch):
    import pytest

    from asset_based_agent.report_review_server.services import model_discovery
    from asset_based_agent.report_review_server.services.auth_service import (
        ServiceError,
    )
    monkeypatch.setattr(model_discovery.socket, "getaddrinfo", lambda *a, **kw: [(2, 1, 6, "", ("127.0.0.1", 443))])
    with pytest.raises(ServiceError):
        model_discovery.fetch_models("https://localhost", "secret")


@pytest.mark.parametrize("status,payload,expected", [
    (200, {"data": [{"id": "one"}, {"id": "two"}, {"id": "one"}]}, ["one", "two"]),
    (401, {"error": "secret"}, "discovery_failed"),
    (302, {}, "discovery_failed"),
    (200, {"data": []}, "discovery_empty"),
    (200, {"data": [{"name": "missing-id"}]}, "discovery_format"),
    (200, {"data": [{"id": "one"}], "has_more": True}, "discovery_pagination"),
])
def test_provider_list_contract(monkeypatch, status, payload, expected):
    from asset_based_agent.report_review_server.services import model_discovery
    from asset_based_agent.report_review_server.services.auth_service import (
        ServiceError,
    )
    monkeypatch.setattr(model_discovery.socket, "getaddrinfo", lambda *a, **kw: [(2, 1, 6, "", ("8.8.8.8", 443))])
    calls = []

    class Connection:
        def __init__(self, host, address):
            assert host == "api.deepseek.com"
            assert address == "8.8.8.8"

        def request(self, method, path, headers):
            calls.append((method, path))
            assert headers["Authorization"] == "Bearer secret"

        def getresponse(self):
            return type("Response", (), {"status": status, "read": lambda self, n: json.dumps(payload).encode()})()

        def close(self):
            pass

    monkeypatch.setattr(model_discovery, "_PinnedHTTPS", Connection)
    if isinstance(expected, list):
        assert model_discovery.fetch_models("https://api.deepseek.com/v1", "secret") == expected
    else:
        with pytest.raises(ServiceError) as error:
            model_discovery.fetch_models("https://api.deepseek.com/v1", "secret")
        assert error.value.code == expected
        assert "secret" not in str(error.value)
    assert calls == [("GET", "/v1/models")]


def test_discovery_validation_does_not_echo_key(client):
    headers = bearer(login(client, "admin", "AdminPassword123!", instance="validation")["access_token"])
    response = client.post("/api/v1/admin/channels/discover", headers=headers,
                           json={"base_url": "https://example.com", "api_key": {"secret-value": "do-not-echo"}})
    assert response.status_code == 422
    assert "do-not-echo" not in response.text


def test_model_form_uses_discovered_selection(client):
    page = client.get("/admin").text
    assert 'id="test-connection" type="button" disabled' in page
    assert 'name="provider_model" id="model-choice" required disabled' in page
    assert '<form id="model">' not in page
