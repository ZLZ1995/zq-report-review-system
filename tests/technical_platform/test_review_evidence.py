def issue(*, description="Synthetic issue", confidence=0.8, evidence=None):
    return {
        "source_file_id": "file-1",
        "source_file_name": "synthetic.docx",
        "category": "consistency",
        "risk_level": "medium",
        "location": {"paragraph": 3},
        "description": description,
        "recommendation": "Check source",
        "confidence": confidence,
        "evidence_summaries": evidence or ["paragraph 3"],
    }


def test_review_issues_receive_stable_evidence_identity_and_exact_duplicates_merge():
    from asset_based_agent.technical_platform.review_issues import (
        normalize_review_result,
    )

    result = normalize_review_result(
        {
            "kind": "review",
            "issues": [
                issue(confidence=0.7, evidence=["first"]),
                issue(confidence=0.9, evidence=["second"]),
            ],
        },
        round_number=1,
    )
    assert len(result["issues"]) == 1
    item = result["issues"][0]
    assert len(item["fingerprint"]) == 64
    assert item["evidence_refs"][0]["source_file_id"] == "file-1"
    assert item["evidence_summaries"] == ["first", "second"]
    assert item["confidence"] == 0.9
    assert item["revision"] == {
        "first_seen_round": 1,
        "last_seen_round": 1,
        "status": "new",
    }


def test_prior_issue_becomes_persistent_and_absent_prior_is_reported_resolved():
    from asset_based_agent.technical_platform.review_issues import (
        normalize_review_result,
    )

    first = normalize_review_result(
        {"kind": "review", "issues": [issue()]}, round_number=1
    )
    second = normalize_review_result(
        {"kind": "review", "issues": [issue()]},
        round_number=2,
        prior_issues=first["issues"],
    )
    assert second["issues"][0]["revision"] == {
        "first_seen_round": 1,
        "last_seen_round": 2,
        "status": "persistent",
    }
    resolved = normalize_review_result(
        {"kind": "review", "issues": []}, round_number=2, prior_issues=first["issues"]
    )
    assert resolved["resolved_issues"] == [
        {
            "fingerprint": first["issues"][0]["fingerprint"],
            "first_seen_round": 1,
            "last_seen_round": 1,
            "status": "resolved",
        }
    ]


def test_missing_evidence_is_explicitly_unverified_not_silently_sufficient():
    from asset_based_agent.technical_platform.review_issues import (
        normalize_review_result,
    )

    item = issue(evidence=[])
    item["evidence_summaries"] = []
    normalized = normalize_review_result({"kind": "review", "issues": [item]})[
        "issues"
    ][0]
    assert normalized["evidence_state"] == "unverified"
    assert normalized["requires_verification"] is True
