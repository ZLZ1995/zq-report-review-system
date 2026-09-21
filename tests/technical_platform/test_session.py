import httpx

from asset_based_agent.report_review_app.services.remote_auth_service import (
    MemoryCredentialStore,
    RemoteSessionClient,
)
from asset_based_agent.technical_platform.session import (
    ConnectionState,
    PlatformSession,
)


def test_first_password_change_precedes_model_access_and_reauthenticates():
    calls = []
    changed = False

    def handler(request):
        nonlocal changed
        path = request.url.path
        calls.append(path)
        if path.endswith("/auth/login"):
            return httpx.Response(
                200,
                json={
                    "access_token": "test-access",
                    "refresh_token": "test-refresh",
                    "user": {
                        "user_id": "u1",
                        "username": "tester",
                        "must_change_password": not changed,
                    },
                },
            )
        if path.endswith("/auth/change-password"):
            changed = True
            return httpx.Response(204)
        if path.endswith("/models"):
            return httpx.Response(200, json=[{"model_id": "m1", "display_name": "M"}])
        return httpx.Response(200, json={"balance": "10.00", "currency": "CNY"})

    client = RemoteSessionClient(
        "https://local.test/api/v1",
        client_instance_id="test",
        credential_store=MemoryCredentialStore(),
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    service = PlatformSession(client)
    assert service.login("tester", "temporary") == {"must_change_password": True}
    assert calls == ["/api/v1/auth/login"]
    result = service.change_password("temporary", "new-password")
    assert result["owner"] and result["models"][0]["model_id"] == "m1"
    assert calls[:3] == [
        "/api/v1/auth/login",
        "/api/v1/auth/change-password",
        "/api/v1/auth/login",
    ]


def test_network_grace_deadline_cannot_be_reset_by_late_probe():
    state = ConnectionState()
    assert state.observe("offline", 10) == "reconnecting"
    assert state.observe("offline", 25) == "reconnecting"
    assert state.observe("ok", 40) == "terminated"
    assert state.observe("ok", 41) == "terminated"


def test_network_recovers_before_deadline_and_revocation_is_immediate():
    state = ConnectionState()
    state.observe("offline", 10)
    assert state.observe("ok", 39) == "connected"
    assert state.observe("revoked", 40) == "terminated"
