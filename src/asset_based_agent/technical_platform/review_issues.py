"""Stable evidence identities and revision metadata for delivered review issues."""

from __future__ import annotations

import json
import re
from copy import deepcopy
from hashlib import sha256


def _clean(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _fingerprint(issue):
    identity = {
        "source_file_id": issue.get("source_file_id"),
        "category": _clean(issue.get("category")).casefold(),
        "location": issue.get("location") or {},
        "description": _clean(issue.get("description")).casefold(),
    }
    encoded = json.dumps(
        identity, sort_keys=True, ensure_ascii=False, separators=(",", ":")
    )
    return sha256(encoded.encode("utf-8")).hexdigest()


def _evidence_refs(issue):
    location = issue.get("location") or {}
    summaries = [
        str(item).strip()
        for item in issue.get("evidence_summaries", [])
        if str(item).strip()
    ]
    original = str(issue.get("original_text") or "").strip()
    evidence = summaries or ([original] if original else [])
    return [
        {
            "source_file_id": issue.get("source_file_id"),
            "location": deepcopy(location),
            "evidence_sha256": sha256(text.encode("utf-8")).hexdigest(),
        }
        for text in evidence
    ]


def normalize_review_result(result, *, round_number=1, prior_issues=()):
    if result.get("kind") != "review":
        return result
    prior = {
        item.get("fingerprint") or _fingerprint(item): item for item in prior_issues
    }
    merged = {}
    for raw in result.get("issues", []):
        item = deepcopy(raw)
        fingerprint = _fingerprint(item)
        summaries = [
            str(value).strip()
            for value in item.get("evidence_summaries", [])
            if str(value).strip()
        ]
        item["fingerprint"] = fingerprint
        item["evidence_summaries"] = summaries
        item["evidence_refs"] = _evidence_refs(item)
        sufficient = bool(item["evidence_refs"])
        item["evidence_state"] = "sufficient" if sufficient else "unverified"
        item["requires_verification"] = (
            bool(item.get("requires_verification")) or not sufficient
        )
        previous = prior.get(fingerprint)
        first = (
            previous.get("revision", {}).get("first_seen_round", round_number)
            if previous
            else round_number
        )
        item["revision"] = {
            "first_seen_round": first,
            "last_seen_round": round_number,
            "status": "persistent" if previous else "new",
        }
        existing = merged.get(fingerprint)
        if existing is None:
            merged[fingerprint] = item
            continue
        combined = list(dict.fromkeys([*existing["evidence_summaries"], *summaries]))
        winner = (
            item
            if item.get("confidence", 0) > existing.get("confidence", 0)
            else existing
        )
        winner["evidence_summaries"] = combined
        winner["evidence_refs"] = _evidence_refs(winner)
        merged[fingerprint] = winner
    current = list(merged.values())
    missing = sorted(set(prior) - set(merged))
    normalized = deepcopy(result)
    normalized["issues"] = current
    normalized["resolved_issues"] = [
        {
            "fingerprint": fingerprint,
            "first_seen_round": prior[fingerprint]
            .get("revision", {})
            .get("first_seen_round", 1),
            "last_seen_round": prior[fingerprint]
            .get("revision", {})
            .get("last_seen_round", round_number - 1),
            "status": "resolved",
        }
        for fingerprint in missing
    ]
    return normalized
