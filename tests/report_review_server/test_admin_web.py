from .conftest import bearer, login


def test_admin_assets_are_independent_and_restrict_scripts(client):
    page = client.get("/admin")
    assert page.status_code == 200
    assert "总控服务台" in page.text
    assert "frame-ancestors 'none'" in page.headers["content-security-policy"]
    assert page.headers["cache-control"] == "no-store"
    script = client.get("/admin/app.js").text
    assert "localStorage" not in script
    assert "innerHTML" not in script
    assert client.get("/admin/style.css").status_code == 200


def test_overview_requires_admin_and_never_exposes_password(client):
    assert client.get("/api/v1/admin/overview").status_code == 401
    admin = login(client, "admin", "AdminPassword123!", instance="web")
    headers = bearer(admin["access_token"])
    created = client.post("/api/v1/admin/users", headers=headers, json={
        "username": "web-user", "display_name": "Web User",
        "temporary_password": "Temporary123",
    })
    assert created.status_code == 201
    result = client.get("/api/v1/admin/overview", headers=headers)
    assert result.status_code == 200
    assert len(result.json()["users"]) == 2
    assert "password_hash" not in result.text
    assert "TemporaryPassword" not in result.text
    user = login(client, "web-user", "Temporary123", instance="customer")
    assert client.get("/api/v1/admin/overview", headers=bearer(user["access_token"])).status_code == 403


def test_route_secret_is_not_returned_in_overview(client):
    admin = login(client, "admin", "AdminPassword123!", instance="web")
    headers = bearer(admin["access_token"])
    model = client.post("/api/v1/admin/models", headers=headers, json={
        "code": "demo", "display_name": "Demo", "tier": "standard",
        "model_multiplier": "1", "max_output_tokens": 8192,
    }).json()
    response = client.post(f"/api/v1/admin/models/{model['model_id']}/routes", headers=headers, json={
        "provider_type": "deepseek", "provider_model": "demo", "base_url": "https://example.com",
        "api_key": "secret-never-return", "priority": 1,
        "rates": dict.fromkeys(["input", "output", "cache_hit", "cache_miss", "reasoning"], "1"),
    })
    assert response.status_code == 201
    overview = client.get("/api/v1/admin/overview", headers=headers)
    assert overview.json()["routes"][0]["api_key_configured"] is True
    assert "secret-never-return" not in overview.text
    assert "ciphertext" not in overview.text
