from .conftest import bearer, login


def draft(version="1.0.0"):
    return {
        "skill_id": "example.review",
        "version": version,
        "package_sha256": "a" * 64,
        "schema_version": 1,
        "adapter": "report.review",
        "capabilities": ["read_selected_files", "generate_artifacts"],
        "minimum_client_version": "0.2.6",
        "evidence_sha256": "b" * 64,
        "test_report_sha256": "c" * 64,
    }


def test_skill_release_requires_admin_test_evidence_and_staged_transition(client):
    token = login(client, "admin", "AdminPassword123!", instance="skill-release")[
        "access_token"
    ]
    headers = bearer(token)
    assert client.post("/api/v1/admin/skill-releases", json=draft()).status_code == 401
    invalid = draft()
    invalid["test_report_sha256"] = "raw customer report"
    assert (
        client.post(
            "/api/v1/admin/skill-releases", headers=headers, json=invalid
        ).status_code
        == 422
    )
    created = client.post("/api/v1/admin/skill-releases", headers=headers, json=draft())
    assert created.status_code == 201, created.text
    release_id = created.json()["release_id"]
    direct = client.post(
        f"/api/v1/admin/skill-releases/{release_id}/transition",
        headers=headers,
        json={"status": "stable"},
    )
    assert direct.status_code == 409
    for status in ("approved", "stable"):
        response = client.post(
            f"/api/v1/admin/skill-releases/{release_id}/transition",
            headers=headers,
            json={"status": status},
        )
        assert response.status_code == 200, response.text
    public = client.get("/api/v1/skill-releases")
    assert public.status_code == 200
    assert public.json()[0]["status"] == "stable"
    assert "evidence_sha256" not in public.text
    assert "test_report_sha256" not in public.text


def test_new_stable_withdraws_old_and_old_can_be_approved_for_rollback(client):
    token = login(client, "admin", "AdminPassword123!", instance="skill-rollback")[
        "access_token"
    ]
    headers = bearer(token)
    ids = []
    for version in ("1.0.0", "1.1.0"):
        created = client.post(
            "/api/v1/admin/skill-releases", headers=headers, json=draft(version)
        )
        ids.append(created.json()["release_id"])
        for status in ("approved", "stable"):
            assert (
                client.post(
                    f"/api/v1/admin/skill-releases/{ids[-1]}/transition",
                    headers=headers,
                    json={"status": status},
                ).status_code
                == 200
            )
    listing = client.get("/api/v1/admin/skill-releases", headers=headers).json()
    states = {item["version"]: item["status"] for item in listing}
    assert states == {"1.0.0": "withdrawn", "1.1.0": "stable"}
    assert (
        client.post(
            f"/api/v1/admin/skill-releases/{ids[0]}/transition",
            headers=headers,
            json={"status": "approved"},
        ).status_code
        == 200
    )
    assert (
        client.post(
            f"/api/v1/admin/skill-releases/{ids[0]}/transition",
            headers=headers,
            json={"status": "stable"},
        ).status_code
        == 200
    )
    public = client.get("/api/v1/skill-releases").json()
    assert [(item["version"], item["status"]) for item in public] == [
        ("1.0.0", "stable")
    ]


def test_skill_release_payload_cannot_contain_rules_or_customer_text(client):
    token = login(client, "admin", "AdminPassword123!", instance="skill-fields")[
        "access_token"
    ]
    payload = draft()
    payload["instructions"] = "private prompt"
    response = client.post(
        "/api/v1/admin/skill-releases", headers=bearer(token), json=payload
    )
    assert response.status_code == 422
    assert "private prompt" not in response.text
