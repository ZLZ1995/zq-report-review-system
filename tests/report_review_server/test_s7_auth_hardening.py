"""S7 认证与安全加固（先红后绿）。

S7-01：客户简化密码格式保持不变（characterization 冻结），但强制登录防护——
连续失败计数锁定、递增重试间隔、管理员重置解锁。
S7-02：refresh token 轮换链——grace 外旧令牌再现即撤销整条 session family；
refresh 绑定 client_instance_id，不匹配即撤销。
"""
from __future__ import annotations

from datetime import timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select

from asset_based_agent.report_review_server.api import create_app
from asset_based_agent.report_review_server.config import ServerSettings
from asset_based_agent.report_review_server.models import AuthSession, utc_now
from asset_based_agent.report_review_server.services.auth_service import (
    bootstrap_admin,
)

from .conftest import bearer, login


def make_client(**overrides) -> TestClient:
    settings = ServerSettings(
        database_url="sqlite+pysqlite:///:memory:",
        jwt_secret="test-secret-that-is-at-least-thirty-two-characters",
        environment="test",
        **overrides,
    )
    app = create_app(settings)
    bootstrap_admin(
        app.state.session_factory,
        username="admin",
        password="AdminPassword123!",
        display_name="Administrator",
    )
    return TestClient(app)


def create_user(client: TestClient, username: str = "s7user",
                password: str = "12345678") -> dict:
    admin = login(client, "admin", "AdminPassword123!", instance="admin-pc")
    response = client.post(
        "/api/v1/admin/users",
        headers=bearer(str(admin["access_token"])),
        json={"username": username, "display_name": username,
              "temporary_password": password},
    )
    assert response.status_code == 201, response.text
    return response.json()


def wrong_login(client: TestClient, username: str = "s7user"):
    return client.post("/api/v1/auth/login", json={
        "username": username, "password": "wrong-pass",
        "client_instance_id": "attacker"})


def refresh(client: TestClient, token: str, **extra):
    return client.post("/api/v1/auth/refresh",
                       json={"refresh_token": token, **extra})


# ------------------------------------------------------------------ S7-01 登录防护

def test_lockout_after_max_failures_blocks_even_correct_password():
    with make_client(login_failure_delay_seconds=0) as client:
        create_user(client)
        for _ in range(5):
            assert wrong_login(client).status_code == 401
        # 连续失败达到上限：账号锁定，正确密码也进不来
        blocked = client.post("/api/v1/auth/login", json={
            "username": "s7user", "password": "12345678",
            "client_instance_id": "user-pc"})
        assert blocked.status_code == 423
        assert blocked.json()["error"]["code"] == "account_locked"


def test_progressive_delay_between_attempts():
    with make_client(login_failure_delay_seconds=30) as client:
        create_user(client)
        # 前两次失败（手误场景）不惩罚
        assert wrong_login(client).status_code == 401
        assert wrong_login(client).status_code == 401
        # 第 3 次失败起进入递增延迟窗口
        assert wrong_login(client).status_code == 401
        delayed = wrong_login(client)
        assert delayed.status_code == 429
        assert delayed.json()["error"]["code"] == "login_too_frequent"


def test_successful_login_resets_failure_counter():
    with make_client(login_failure_delay_seconds=0) as client:
        create_user(client)
        for _ in range(4):
            assert wrong_login(client).status_code == 401
        login(client, "s7user", "12345678", instance="user-pc")
        # 计数已清零：再失败 4 次仍不应锁定
        for _ in range(4):
            assert wrong_login(client).status_code == 401
        fifth = wrong_login(client)
        assert fifth.status_code == 401  # 第 5 次触发锁定，但响应仍是 401
        sixth = client.post("/api/v1/auth/login", json={
            "username": "s7user", "password": "12345678",
            "client_instance_id": "user-pc"})
        assert sixth.status_code == 423


def test_admin_reset_unlocks_account():
    with make_client(login_failure_delay_seconds=0) as client:
        user = create_user(client)
        for _ in range(5):
            assert wrong_login(client).status_code == 401
        assert wrong_login(client).status_code in (401, 423)
        admin = login(client, "admin", "AdminPassword123!", instance="admin-pc")
        reset = client.post(
            f"/api/v1/admin/users/{user['user_id']}/reset-password",
            headers=bearer(str(admin["access_token"])),
            json={"temporary_password": "Replacement1"},
        )
        assert reset.status_code == 204
        # 管理员重置即解锁
        login(client, "s7user", "Replacement1", instance="user-pc")


def test_unknown_username_behaves_identically_no_enumeration():
    with make_client(login_failure_delay_seconds=0) as client:
        create_user(client)
        for _ in range(5):
            assert wrong_login(client, username="ghost").status_code == 401
        # 不存在的账号同样进入锁定语义，避免"锁定即存在"枚举预言机
        assert wrong_login(client, username="ghost").status_code in (401, 423)
        # 对 ghost 的锁定不得影响真实用户
        login(client, "s7user", "12345678", instance="user-pc")


# ------------------------------------------------------------------ S7-02 轮换链与重用检测

def _rewind_rotation(client: TestClient, user_id: str, seconds: int = 3600) -> None:
    with client.app.state.session_factory() as db:
        session = db.scalar(select(AuthSession).where(
            AuthSession.user_id == user_id))
        session.refresh_rotated_at = utc_now() - timedelta(seconds=seconds)
        db.commit()


def test_reuse_beyond_grace_revokes_whole_family():
    with make_client() as client:
        create_user(client)
        first_login = login(client, "s7user", "12345678", instance="user-pc")
        rotated = refresh(client, str(first_login["refresh_token"]))
        assert rotated.status_code == 200
        # 篡改时间：旧令牌已超出 grace
        _rewind_rotation(client, str(first_login["user"]["user_id"]))
        stale = refresh(client, str(first_login["refresh_token"]))
        assert stale.status_code == 401
        # 整条 session family 必须被撤销：当前令牌也随之失效
        current = refresh(client, str(rotated.json()["refresh_token"]))
        assert current.status_code == 401
        with client.app.state.session_factory() as db:
            session = db.scalar(select(AuthSession).where(
                AuthSession.user_id == str(first_login["user"]["user_id"])))
            assert session.revoked_at is not None
            assert session.revoked_reason == "refresh_token_reuse_detected"


def test_reuse_within_grace_still_allowed_guard():
    """既有 grace 行为守护：窗口内旧令牌可用且不撤销。"""
    with make_client() as client:
        create_user(client)
        first_login = login(client, "s7user", "12345678", instance="user-pc")
        assert refresh(client, str(first_login["refresh_token"])).status_code == 200
        # 窗口内再次用旧令牌（双进程并发场景）必须放行
        replay = refresh(client, str(first_login["refresh_token"]))
        assert replay.status_code == 200
        with client.app.state.session_factory() as db:
            session = db.scalar(select(AuthSession).where(
                AuthSession.user_id == str(first_login["user"]["user_id"])))
            assert session.revoked_at is None


def test_client_instance_mismatch_revokes_family():
    with make_client() as client:
        create_user(client)
        first_login = login(client, "s7user", "12345678", instance="user-pc")
        mismatched = refresh(client, str(first_login["refresh_token"]),
                             client_instance_id="attacker-laptop")
        assert mismatched.status_code == 401
        assert mismatched.json()["error"]["code"] == "invalid_refresh_token"
        with client.app.state.session_factory() as db:
            session = db.scalar(select(AuthSession).where(
                AuthSession.user_id == str(first_login["user"]["user_id"])))
            assert session.revoked_at is not None
            assert session.revoked_reason == "client_instance_mismatch"


def test_client_instance_match_rotates_normally():
    with make_client() as client:
        create_user(client)
        first_login = login(client, "s7user", "12345678", instance="user-pc")
        rotated = refresh(client, str(first_login["refresh_token"]),
                          client_instance_id="user-pc")
        assert rotated.status_code == 200
        # 旧客户端不带 instance id 的 refresh 保持兼容
        legacy = refresh(client, str(rotated.json()["refresh_token"]))
        assert legacy.status_code == 200
