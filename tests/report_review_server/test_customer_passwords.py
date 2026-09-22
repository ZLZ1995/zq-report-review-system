import pytest

from .conftest import bearer, login


@pytest.mark.parametrize("password", ["12345678", "Ab123456", "1234567890123456"])
def test_customer_create_accepts_new_policy(client, password):
    headers = bearer(login(client, "admin", "AdminPassword123!", instance="policy")["access_token"])
    result = client.post("/api/v1/admin/users", headers=headers, json={
        "username": "policy", "display_name": "Policy", "temporary_password": password})
    assert result.status_code == 201
    assert login(client, "policy", password, instance="user")["user"]["must_change_password"]


@pytest.mark.parametrize("password", ["1234567", "12345678901234567", "abcdefgh", "Ab12345!", "1234567 ", "密码12345678"])
def test_customer_create_rejects_invalid_password(client, password):
    headers = bearer(login(client, "admin", "AdminPassword123!", instance="policy")["access_token"])
    result = client.post("/api/v1/admin/users", headers=headers, json={
        "username": "policy", "display_name": "Policy", "temporary_password": password})
    assert result.status_code == 422


def test_change_reset_and_case_sensitive_login(client):
    headers = bearer(login(client, "admin", "AdminPassword123!", instance="policy")["access_token"])
    created = client.post("/api/v1/admin/users", headers=headers, json={
        "username": "policy", "display_name": "Policy", "temporary_password": "12345678"})
    assert created.status_code == 201
    user = login(client, "policy", "12345678", instance="user")
    changed = client.post("/api/v1/auth/change-password", headers=bearer(user["access_token"]),
                          json={"current_password": "12345678", "new_password": "Ab123456"})
    assert changed.status_code == 204
    assert client.post("/api/v1/auth/login", json={"username": "policy", "password": "ab123456", "client_instance_id": "case"}).status_code == 401
    assert not login(client, "policy", "Ab123456", instance="user")["user"]["must_change_password"]
    reset = client.post(f"/api/v1/admin/users/{created.json()['user_id']}/reset-password", headers=headers,
                        json={"temporary_password": "87654321"})
    assert reset.status_code == 204
    assert login(client, "policy", "87654321", instance="reset")["user"]["must_change_password"]


def test_admin_policy_unchanged_and_legacy_hashes_still_verify():
    from asset_based_agent.report_review_server.security import (
        hash_password,
        verify_password,
    )
    with pytest.raises(ValueError):
        hash_password("12345678")
    legacy = hash_password("LegacyPassword123!")
    assert verify_password("LegacyPassword123!", legacy)
    assert not verify_password("legacypassword123!", legacy)
