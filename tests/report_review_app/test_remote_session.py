from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from asset_based_agent.report_review_app.services.remote_auth_service import (
    ConnectivitySupervisor,
    InsufficientBalance,
    MemoryCredentialStore,
    NetworkUnavailable,
    RemoteAuthenticationError,
    RemoteAuthService,
    RemoteSessionClient,
    SessionRevoked,
    WindowsCredentialStore,
    load_or_create_client_instance_id,
)


def _token_payload(access: str, refresh: str) -> dict[str, object]:
    return {
        "access_token": access,
        "refresh_token": refresh,
        "token_type": "bearer",
        "expires_in": 900,
        "user": {
            "user_id": "USER-1",
            "username": "reviewer",
            "display_name": "Reviewer",
            "role": "user",
            "status": "active",
            "must_change_password": False,
        },
    }


@pytest.mark.parametrize('invalid', [False, True])
def test_understanding_client_preflights_and_revalidates_model_output(invalid):
    calls = []
    def handler(request):
        calls.append(request.url.path)
        if request.method == 'GET':
            return httpx.Response(200, json={'schema_version': 1, 'protocol_version': 1,
                                           'capabilities': {'task_understanding': 1}})
        assert request.url.path == '/api/v1/agent/understand'
        assert request.headers['authorization'] == 'Bearer synthetic'
        return httpx.Response(200, json={
            'schema_version': 1, 'message_intent': 'consult', 'goal': '',
            'targets': ['invented'] if invalid else [], 'references': [], 'excluded': [],
            'constraints': [], 'deliverables': [], 'missing_inputs': [],
            'evidence_message_ids': ['msg'], 'skill_ids': [], 'next_action': 'answer',
            'reply': '只读审核，不改原文件。',
        })
    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        client = RemoteSessionClient('https://review.example/api/v1', client_instance_id='test',
                                     credential_store=MemoryCredentialStore(), http_client=http)
        client.access_token = 'synthetic'
        payload = {'request_id': 'r', 'model_id': 'm', 'message_id': 'msg', 'prompt': '解释审核'}
        if invalid:
            with pytest.raises(RemoteAuthenticationError, match='理解'):
                client.understand_task(payload)
        else:
            assert client.understand_task(payload)['next_action'] == 'answer'
    assert calls == ['/api/v1/capabilities', '/api/v1/agent/understand']


@pytest.mark.parametrize('cancel_before', [True, False])
def test_understanding_cancel_during_precheck_does_not_post(cancel_before):
    import threading

    from asset_based_agent.report_review_app.services.task_cancellation import (
        TaskCancelled,
    )
    cancel = threading.Event()
    calls = []
    if cancel_before:
        cancel.set()
    def handler(request):
        calls.append(request.method)
        assert request.method == 'GET'
        cancel.set()
        return httpx.Response(200, json={'schema_version': 1, 'protocol_version': 1,
                                       'capabilities': {'task_understanding': 1}})
    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        client = RemoteSessionClient('https://review.example/api/v1', client_instance_id='test',
                                     credential_store=MemoryCredentialStore(), http_client=http)
        client.access_token = 'synthetic'
        with pytest.raises(TaskCancelled):
            client.understand_task({'request_id': 'r', 'model_id': 'm', 'message_id': 'msg',
                                    'prompt': '解释审核'}, cancel=cancel)
    assert calls == ([] if cancel_before else ['GET'])


def test_missing_routing_endpoint_has_compatibility_error_without_retry():
    from asset_based_agent.report_review_app.services.remote_auth_service import (
        ServerCapabilityUnavailable,
    )
    calls = []
    def handler(request):
        calls.append(request)
        if request.url.path.endswith('/capabilities'):
            return httpx.Response(200, json={'schema_version': 1, 'protocol_version': 1,
                                           'capabilities': {'skill_routing': 1}})
        return httpx.Response(404, json={'detail': 'Not Found'})
    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        client = RemoteSessionClient('https://review.example', client_instance_id='test',
                                     credential_store=MemoryCredentialStore(), http_client=http)
        client.access_token = 'synthetic-token'
        with pytest.raises(ServerCapabilityUnavailable, match='接口'):
            client.route_skill({'prompt': 'synthetic'})
    assert len(calls) == 2
    assert sum(request.method == 'POST' for request in calls) == 1


def test_remote_login_persists_only_refresh_token() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=_token_payload("ACCESS-1", "REFRESH-1"))

    credentials = MemoryCredentialStore()
    http_client = httpx.Client(transport=httpx.MockTransport(handler))
    client = RemoteSessionClient(
        "https://review.example/api/v1",
        client_instance_id="CLIENT-1",
        credential_store=credentials,
        http_client=http_client,
    )

    user = client.login("reviewer", "Password123!")

    assert user == {"username": "reviewer", "display_name": "Reviewer"}
    assert client.access_token == "ACCESS-1"
    assert credentials.get("CLIENT-1") == "REFRESH-1"
    assert "ACCESS-1" not in json.dumps(credentials.values)
    assert requests[0].url.path == "/api/v1/auth/login"


def test_windows_credential_store_uses_generic_credential_api(monkeypatch) -> None:
    persisted: dict[str, object] = {}

    class FakeWindowsError(Exception):
        winerror = 1168

    def write(payload: dict[str, object], flags: int) -> None:
        assert flags == 0
        assert isinstance(payload["CredentialBlob"], str)
        persisted.update(payload)

    def read(target: str, credential_type: int) -> dict[str, object]:
        assert target == "ZQReportReview:refresh:CLIENT-WIN"
        assert credential_type == 1
        if not persisted:
            raise FakeWindowsError()
        return {"CredentialBlob": persisted["CredentialBlob"].encode("utf-16-le")}

    def delete(target: str, credential_type: int) -> None:
        assert target == "ZQReportReview:refresh:CLIENT-WIN"
        assert credential_type == 1
        persisted.clear()

    fake_win32cred = SimpleNamespace(
        CRED_TYPE_GENERIC=1,
        CRED_PERSIST_LOCAL_MACHINE=2,
        CredWrite=write,
        CredRead=read,
        CredDelete=delete,
    )
    monkeypatch.setitem(sys.modules, "win32cred", fake_win32cred)
    monkeypatch.setitem(sys.modules, "pywintypes", SimpleNamespace(error=FakeWindowsError))
    store = WindowsCredentialStore()

    assert store.get("CLIENT-WIN") is None
    store.set("CLIENT-WIN", "REFRESH-WIN")
    assert store.get("CLIENT-WIN") == "REFRESH-WIN"
    store.delete("CLIENT-WIN")
    assert store.get("CLIENT-WIN") is None


def test_heartbeat_refreshes_expired_access_token_and_rotates_credential() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if request.url.path.endswith("/auth/login"):
            return httpx.Response(200, json=_token_payload("ACCESS-OLD", "REFRESH-OLD"))
        if request.url.path.endswith("/auth/refresh"):
            return httpx.Response(200, json=_token_payload("ACCESS-NEW", "REFRESH-NEW"))
        if request.headers.get("Authorization") == "Bearer ACCESS-OLD":
            return httpx.Response(
                401,
                json={"error": {"code": "invalid_access_token", "message": "expired"}},
            )
        return httpx.Response(200, json={"status": "ok"})

    credentials = MemoryCredentialStore()
    client = RemoteSessionClient(
        "https://review.example/api/v1",
        client_instance_id="CLIENT-2",
        credential_store=credentials,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    client.login("reviewer", "Password123!")

    client.heartbeat()

    assert calls == [
        "/api/v1/auth/login",
        "/api/v1/auth/heartbeat",
        "/api/v1/auth/refresh",
        "/api/v1/auth/heartbeat",
    ]
    assert client.access_token == "ACCESS-NEW"
    assert credentials.get("CLIENT-2") == "REFRESH-NEW"


def test_remote_client_exposes_model_balance_and_review_job_business_endpoints() -> None:
    paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        if request.url.path.endswith("/auth/login"):
            return httpx.Response(200, json=_token_payload("ACCESS", "REFRESH"))
        if request.url.path.endswith("/models"):
            return httpx.Response(
                200,
                json=[
                    {
                        "model_id": "MODEL-1",
                        "code": "deepseek-chat",
                        "display_name": "DeepSeek Chat",
                        "tier": "standard",
                    }
                ],
            )
        if request.url.path.endswith("/account/balance"):
            return httpx.Response(200, json={"balance": "12.34", "currency": "CNY"})
        if request.url.path.endswith('/capabilities'):
            return httpx.Response(200, json={'schema_version': 1, 'protocol_version': 1,
                                           'capabilities': {'review_jobs': 1}})
        if request.url.path.endswith("/review-jobs"):
            return httpx.Response(201, json={"job_id": "JOB-1", "status": "queued"})
        if request.url.path.endswith("/execute"):
            return httpx.Response(
                200,
                json={"job_id": "JOB-1", "status": "succeeded", "issues": []},
            )
        if request.url.path.endswith("/events"):
            assert request.url.params["after_sequence"] == "2"
            return httpx.Response(200, json=[{
                "sequence": 3,
                "kind": "running",
                "completed_batches": 0,
                "created_at": "2026-09-17T00:00:00Z",
            }])
        raise AssertionError(request.url.path)

    client = RemoteSessionClient(
        "https://review.example/api/v1",
        client_instance_id="CLIENT-BUSINESS",
        credential_store=MemoryCredentialStore(),
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    client.login("reviewer", "Password123!")

    assert client.list_models()[0]["model_id"] == "MODEL-1"
    assert client.get_balance() == {"balance": "12.34", "currency": "CNY"}
    created = client.create_review_job(
        {
            "client_job_id": "CLIENT-JOB",
            "model_id": "MODEL-1",
            "round_number": 1,
            "chunks": [],
        }
    )
    result = client.execute_review_job(str(created["job_id"]))
    events = client.get_review_job_events("JOB-1", after_sequence=2)

    assert result["status"] == "succeeded"
    assert events[0]["sequence"] == 3
    assert paths == [
        "/api/v1/auth/login",
        "/api/v1/models",
        "/api/v1/account/balance",
        "/api/v1/capabilities",
        "/api/v1/review-jobs",
        "/api/v1/review-jobs/JOB-1/execute",
        "/api/v1/review-jobs/JOB-1/events",
    ]


def test_remote_client_preserves_insufficient_balance_business_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith('/capabilities'):
            return httpx.Response(200, json={'schema_version': 1, 'protocol_version': 1,
                                           'capabilities': {'review_jobs': 1}})
        if request.url.path.endswith("/auth/login"):
            return httpx.Response(200, json=_token_payload("ACCESS", "REFRESH"))
        return httpx.Response(
            409,
            json={
                "error": {
                    "code": "insufficient_balance",
                    "message": "余额不足，无法冻结本轮审核额度。",
                }
            },
        )

    client = RemoteSessionClient(
        "https://review.example/api/v1",
        client_instance_id="CLIENT-BALANCE",
        credential_store=MemoryCredentialStore(),
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    client.login("reviewer", "Password123!")

    with pytest.raises(InsufficientBalance, match="余额不足"):
        client.create_review_job({})


def test_connectivity_supervisor_allows_30_seconds_then_checkpoints_and_exits() -> None:
    events: list[str] = []

    def unavailable() -> None:
        raise NetworkUnavailable("offline")

    supervisor = ConnectivitySupervisor(
        unavailable,
        checkpoint=lambda: events.append("checkpoint"),
        force_exit=lambda: events.append("exit"),
        heartbeat_interval_seconds=10,
        reconnect_grace_seconds=30,
    )

    assert supervisor.tick(now=10) == "reconnecting"
    assert supervisor.tick(now=39) == "reconnecting"
    assert events == []
    assert supervisor.tick(now=40) == "terminated"
    assert events == ["checkpoint", "exit"]


def test_revoked_session_checkpoints_and_exits_immediately() -> None:
    events: list[str] = []

    def revoked() -> None:
        raise SessionRevoked("replaced")

    supervisor = ConnectivitySupervisor(
        revoked,
        checkpoint=lambda: events.append("checkpoint"),
        force_exit=lambda: events.append("exit"),
    )

    assert supervisor.tick(now=10) == "terminated"
    assert events == ["checkpoint", "exit"]


def test_expired_remote_credentials_are_treated_as_terminal_session() -> None:
    events: list[str] = []

    def expired() -> None:
        raise RemoteAuthenticationError("expired")

    supervisor = ConnectivitySupervisor(
        expired,
        checkpoint=lambda: events.append("checkpoint"),
        force_exit=lambda: events.append("exit"),
    )

    assert supervisor.tick(now=10) == "terminated"
    assert events == ["checkpoint", "exit"]


def test_checkpoint_failure_does_not_prevent_forced_exit() -> None:
    events: list[str] = []

    def revoked() -> None:
        raise SessionRevoked("replaced")

    def broken_checkpoint() -> None:
        events.append("checkpoint")
        raise OSError("disk full")

    supervisor = ConnectivitySupervisor(
        revoked,
        checkpoint=broken_checkpoint,
        force_exit=lambda: events.append("exit"),
    )

    assert supervisor.tick(now=10) == "terminated"
    assert events == ["checkpoint", "exit"]


def test_client_instance_id_is_stable_and_contains_no_secret(tmp_path: Path) -> None:
    path = tmp_path / "client-instance.json"

    first = load_or_create_client_instance_id(path)
    second = load_or_create_client_instance_id(path)

    assert first == second
    assert len(first) >= 32
    assert json.loads(path.read_text(encoding="utf-8")) == {"client_instance_id": first}


def test_remote_auth_service_maps_network_failure_to_login_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("offline", request=request)

    client = RemoteSessionClient(
        "https://review.example/api/v1",
        client_instance_id="CLIENT-3",
        credential_store=MemoryCredentialStore(),
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    with pytest.raises(NetworkUnavailable):
        RemoteAuthService(client).authenticate("reviewer", "Password123!")
