from __future__ import annotations

from fastapi.testclient import TestClient

from .conftest import bearer, login


def _create_user(client: TestClient, admin_token: str) -> dict[str, object]:
    response = client.post(
        "/api/v1/admin/users",
        headers=bearer(admin_token),
        json={
            "username": "reviewer",
            "display_name": "Reviewer",
            "temporary_password": "Temporary123",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_health_endpoint_does_not_disclose_configuration(
    client: TestClient,
) -> None:
    response = client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "report-review-server"}
    assert "database" not in response.text.lower()
    assert "secret" not in response.text.lower()


def test_admin_creates_user_with_mandatory_password_change(
    client: TestClient,
) -> None:
    admin = login(
        client,
        "admin",
        "AdminPassword123!",
        instance="admin-desktop",
    )

    user = _create_user(client, str(admin["access_token"]))
    user_session = login(
        client,
        "reviewer",
        "Temporary123",
        instance="reviewer-desktop",
    )

    assert user["username"] == "reviewer"
    assert user["must_change_password"] is True
    assert user_session["user"]["must_change_password"] is True
    assert "password" not in user


def test_new_login_revokes_previous_session(client: TestClient) -> None:
    admin = login(
        client,
        "admin",
        "AdminPassword123!",
        instance="admin-desktop",
    )
    _create_user(client, str(admin["access_token"]))
    first = login(
        client,
        "reviewer",
        "Temporary123",
        instance="desktop-a",
    )

    second = login(
        client,
        "reviewer",
        "Temporary123",
        instance="desktop-b",
    )

    old_heartbeat = client.post(
        "/api/v1/auth/heartbeat",
        headers=bearer(str(first["access_token"])),
    )
    new_heartbeat = client.post(
        "/api/v1/auth/heartbeat",
        headers=bearer(str(second["access_token"])),
    )
    assert old_heartbeat.status_code == 401
    assert old_heartbeat.json()["error"]["code"] == "session_revoked"
    assert new_heartbeat.status_code == 200


def test_refresh_token_is_rotated_and_cannot_be_reused(
    client: TestClient,
) -> None:
    """S06 起 refresh 改为宽容窗口语义：

    - 每次 refresh 仍轮换 token（新 != 旧）；
    - 宽容窗口内旧 token 可用（双进程客户端不互相注销）；
    - 超出宽容窗口后旧 token 必须被拒绝（不可无限复用）。
    """
    from datetime import timedelta

    from sqlalchemy import select

    from asset_based_agent.report_review_server.models import (
        AuthSession,
        utc_now,
    )

    session = login(
        client,
        "admin",
        "AdminPassword123!",
        instance="admin-desktop",
    )

    refreshed = client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": session["refresh_token"]},
    )
    assert refreshed.status_code == 200
    assert refreshed.json()["refresh_token"] != session["refresh_token"]

    # 宽容窗口内：旧 token 仍被接受（并发进程容忍）
    reused_in_grace = client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": session["refresh_token"]},
    )
    assert reused_in_grace.status_code == 200

    # 超出宽容窗口：旧 token 必须拒绝
    with client.app.state.session_factory() as db:
        auth_session = db.scalar(
            select(AuthSession).where(
                AuthSession.user_id == session["user"]["user_id"]
            )
        )
        auth_session.refresh_rotated_at = utc_now() - timedelta(seconds=3600)
        db.commit()
    reused_beyond_grace = client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": session["refresh_token"]},
    )
    assert reused_beyond_grace.status_code == 401
    assert reused_beyond_grace.json()["error"]["code"] == "invalid_refresh_token"


def test_admin_password_reset_revokes_user_session(
    client: TestClient,
) -> None:
    admin = login(
        client,
        "admin",
        "AdminPassword123!",
        instance="admin-desktop",
    )
    user = _create_user(client, str(admin["access_token"]))
    old_session = login(
        client,
        "reviewer",
        "Temporary123",
        instance="reviewer-desktop",
    )

    reset = client.post(
        f"/api/v1/admin/users/{user['user_id']}/reset-password",
        headers=bearer(str(admin["access_token"])),
        json={"temporary_password": "Replacement123"},
    )
    old_heartbeat = client.post(
        "/api/v1/auth/heartbeat",
        headers=bearer(str(old_session["access_token"])),
    )
    replacement = login(
        client,
        "reviewer",
        "Replacement123",
        instance="reviewer-new-login",
    )

    assert reset.status_code == 204
    assert old_heartbeat.status_code == 401
    assert replacement["user"]["must_change_password"] is True


def test_user_changes_temporary_password_and_must_log_in_again(
    client: TestClient,
) -> None:
    admin = login(
        client,
        "admin",
        "AdminPassword123!",
        instance="admin-desktop",
    )
    _create_user(client, str(admin["access_token"]))
    user = login(
        client,
        "reviewer",
        "Temporary123",
        instance="reviewer-desktop",
    )

    changed = client.post(
        "/api/v1/auth/change-password",
        headers=bearer(str(user["access_token"])),
        json={
            "current_password": "Temporary123",
            "new_password": "Permanent123",
        },
    )
    revoked = client.post(
        "/api/v1/auth/heartbeat",
        headers=bearer(str(user["access_token"])),
    )
    new_session = login(
        client,
        "reviewer",
        "Permanent123",
        instance="reviewer-desktop",
    )

    assert changed.status_code == 204
    assert revoked.status_code == 401
    assert new_session["user"]["must_change_password"] is False


def test_non_admin_cannot_create_accounts(client: TestClient) -> None:
    admin = login(
        client,
        "admin",
        "AdminPassword123!",
        instance="admin-desktop",
    )
    _create_user(client, str(admin["access_token"]))
    user = login(
        client,
        "reviewer",
        "Temporary123",
        instance="reviewer-desktop",
    )

    response = client.post(
        "/api/v1/admin/users",
        headers=bearer(str(user["access_token"])),
        json={
            "username": "another",
            "display_name": "Another",
            "temporary_password": "Another123",
        },
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "admin_required"


def test_logout_revokes_current_session(client: TestClient) -> None:
    session = login(
        client,
        "admin",
        "AdminPassword123!",
        instance="admin-desktop",
    )
    headers = bearer(str(session["access_token"]))

    logout = client.post("/api/v1/auth/logout", headers=headers)
    heartbeat = client.post("/api/v1/auth/heartbeat", headers=headers)

    assert logout.status_code == 204
    assert heartbeat.status_code == 401
    assert heartbeat.json()["error"]["code"] == "session_revoked"


def test_invalid_credentials_do_not_reveal_whether_user_exists(
    client: TestClient,
) -> None:
    wrong_password = client.post(
        "/api/v1/auth/login",
        json={
            "username": "admin",
            "password": "WrongPassword123!",
            "client_instance_id": "desktop-a",
        },
    )
    missing_user = client.post(
        "/api/v1/auth/login",
        json={
            "username": "missing",
            "password": "WrongPassword123!",
            "client_instance_id": "desktop-b",
        },
    )

    assert wrong_password.status_code == 401
    assert missing_user.status_code == 401
    assert wrong_password.json() == missing_user.json()


def test_duplicate_username_is_rejected(client: TestClient) -> None:
    admin = login(
        client,
        "admin",
        "AdminPassword123!",
        instance="admin-desktop",
    )
    token = str(admin["access_token"])
    _create_user(client, token)

    response = client.post(
        "/api/v1/admin/users",
        headers=bearer(token),
        json={
            "username": "reviewer",
            "display_name": "Duplicate",
            "temporary_password": "Duplicate123",
        },
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "username_exists"
