from __future__ import annotations

import base64

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from .conftest import bearer, login


def _manifest(sequence: int = 1) -> dict[str, object]:
    return {"payload": {"schema_version": 1, "key_id": "zq-release-test", "sequence": sequence,
        "version": f"0.2.{sequence}", "platform": "windows", "arch": "x64",
        "url": "https://example.com/releases/client.zip", "size": 1, "sha256": "a" * 64,
        "protocol_min": 1, "protocol_max": 1, "data_schema_min": 1, "data_schema_max": 10,
        "minimum_updater": "0.1.0", "issued_at": 1, "expires_at": 4_000_000_000, "notes": "test"},
        "signature": "test-signature"}


def test_release_registry_requires_signed_manifest_and_audits_transitions(client, monkeypatch):
    from asset_based_agent.report_review_server.services import client_release_service
    from asset_based_agent.report_review_server.services.client_release_service import DOMAIN, canonical_payload
    private_key = Ed25519PrivateKey.generate()
    key_id = "test-release-key"
    monkeypatch.setattr(client_release_service, "PUBLIC_KEYS", {key_id: private_key.public_key().public_bytes_raw()})
    manifest = _manifest()
    manifest["payload"]["key_id"] = key_id
    manifest["signature"] = base64.b64encode(private_key.sign(DOMAIN + canonical_payload(manifest["payload"]))).decode("ascii")
    token = login(client, "admin", "AdminPassword123!", instance="release-test")["access_token"]
    headers = bearer(token)
    assert client.post("/api/v1/admin/client-releases", headers=headers, json={"manifest": _manifest()}).status_code == 422
    created = client.post("/api/v1/admin/client-releases", headers=headers, json={"manifest": manifest})
    assert created.status_code == 201, created.text
    release_id = created.json()["release_id"]
    assert client.get("/api/v1/client-releases/current").status_code == 404
    transitioned = client.post(f"/api/v1/admin/client-releases/{release_id}/transition", headers=headers, json={"status": "stable"})
    assert transitioned.status_code == 200
    current = client.get("/api/v1/client-releases/current")
    assert current.status_code == 200 and current.json()["manifest"]["payload"]["sequence"] == 1


def test_release_registry_does_not_allow_non_admin_mutation(client):
    assert client.post("/api/v1/admin/client-releases", json={"manifest": _manifest()}).status_code == 401
