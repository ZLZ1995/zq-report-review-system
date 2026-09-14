from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def test_review_job_openapi_contract_is_valid_and_visibility_is_closed() -> None:
    path = ROOT / "docs" / "report_review_productization" / "openapi-v1.yaml"
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))

    assert payload["openapi"] == "3.1.0"
    assert "/review-jobs" in payload["paths"]
    assert "/review-jobs/{job_id}" in payload["paths"]
    assert "/review-jobs/{job_id}/execute" in payload["paths"]
    chunk = payload["components"]["schemas"]["ReviewChunk"]
    assert chunk["additionalProperties"] is False
    assert chunk["properties"]["sheet_state"]["enum"] == ["visible"]
