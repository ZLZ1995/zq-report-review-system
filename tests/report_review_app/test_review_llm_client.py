from __future__ import annotations

import json

import pytest

from asset_based_agent.report_review_app.domain.enums import (
    FileRole,
    IssueStatus,
    RiskLevel,
)
from asset_based_agent.report_review_app.domain.models import IssueLocation, ReviewIssue
from asset_based_agent.report_review_app.services.agent_gateway import (
    AdviceRequest,
    AdviceResult,
    ConversationMessage,
    ConversationTurnRequest,
)
from asset_based_agent.report_review_app.services.document_extraction_service import (
    DocumentChunk,
)
from asset_based_agent.report_review_app.services.privacy_filter import ReviewBatch
from asset_based_agent.report_review_app.services.review_llm_client import (
    OpenAICompatibleReviewLlm,
    ReviewNetworkError,
    ReviewResponseSchemaError,
)


def test_review_llm_parses_structured_findings(monkeypatch) -> None:
    client = OpenAICompatibleReviewLlm(
        {
            "api_base": "https://example.invalid",
            "api_key": "test-key",
            "model": "test-model",
            "wire_api": "chat",
        }
    )
    response = {
        "issues": [
            {
                "source_file_id": "FILE-1",
                "source_file_name": "report.docx",
                "category": "data_inconsistency",
                "risk_level": "high",
                "location": {"paragraph": 1},
                "original_text": "100",
                "description": "value mismatch",
                "confidence": 0.9,
                "rule_id": "llm.review.v1",
            }
        ]
    }
    monkeypatch.setattr(
        client,
        "_post_json",
        lambda _url, _payload: {
            "choices": [{"message": {"content": json.dumps(response)}}]
        },
    )
    batch = ReviewBatch(
        batch_id="BATCH-0001",
        character_count=4,
        chunks=[
            DocumentChunk(
                chunk_id="chunk-1",
                source_file_id="FILE-1",
                source_file_name="report.docx",
                role=FileRole.MAIN_REPORT,
                text="text",
                location=IssueLocation(paragraph=1),
            )
        ],
    )

    findings = client.review_batches([batch])

    assert len(findings) == 1
    assert findings[0].source_file_id == "FILE-1"
    assert findings[0].risk_level.value == "high"


def test_review_llm_normalizes_structured_evidence_summaries(monkeypatch) -> None:
    client = OpenAICompatibleReviewLlm(
        {
            "api_base": "https://api.deepseek.com",
            "api_key": "test-key",
            "model": "test-model",
            "provider": "deepseek",
            "wire_api": "chat_completions",
        }
    )
    response = {
        "issues": [
            {
                "source_file_id": "FILE-1",
                "source_file_name": "report.docx",
                "category": "data_inconsistency",
                "risk_level": "high",
                "location": {"paragraph": 1},
                "original_text": "100",
                "description": "value mismatch",
                "evidence_summaries": [
                    {"content": "first evidence", "paragraph": 227},
                    {"summary": "second evidence", "page": 10},
                    "third evidence",
                ],
                "confidence": 0.9,
                "rule_id": "llm.review.v1",
            }
        ]
    }
    monkeypatch.setattr(
        client,
        "_post_json",
        lambda _url, _payload: {
            "choices": [{"message": {"content": json.dumps(response)}}]
        },
    )

    findings = client.review_batches([_review_batch()])

    assert findings[0].evidence_summaries == [
        "第227段：first evidence",
        "第10页：second evidence",
        "third evidence",
    ]


def test_review_prompt_explicitly_requires_string_evidence_items() -> None:
    client = OpenAICompatibleReviewLlm(
        {
            "api_base": "https://example.invalid",
            "api_key": "test-key",
            "model": "test-model",
            "provider": "openai-compatible",
            "wire_api": "chat_completions",
        }
    )

    payload = client._request_payload(_review_batch())
    prompt = payload["messages"][1]["content"]

    assert '"evidence_summaries": ["' in prompt
    assert "evidence_summaries 必须是字符串数组" in prompt


def test_review_llm_rejects_unknown_evidence_object_without_echoing_content(
    monkeypatch,
) -> None:
    client = OpenAICompatibleReviewLlm(
        {
            "api_base": "https://example.invalid",
            "api_key": "test-key",
            "model": "test-model",
            "provider": "openai-compatible",
            "wire_api": "chat_completions",
        }
    )
    secret_report_text = "CONFIDENTIAL-REPORT-CONTENT"
    response = {
        "issues": [
            {
                "source_file_id": "FILE-1",
                "source_file_name": "report.docx",
                "category": "data_inconsistency",
                "risk_level": "high",
                "location": {"paragraph": 1},
                "description": "value mismatch",
                "evidence_summaries": [{"unknown": secret_report_text}],
                "confidence": 0.9,
                "rule_id": "llm.review.v1",
            }
        ]
    }
    monkeypatch.setattr(
        client,
        "_post_json",
        lambda _url, _payload: {
            "choices": [{"message": {"content": json.dumps(response)}}]
        },
    )

    with pytest.raises(ReviewResponseSchemaError) as exc_info:
        client.review_batches([_review_batch()])

    assert "issues.0.evidence_summaries.0" in str(exc_info.value)
    assert secret_report_text not in str(exc_info.value)


def test_review_llm_retries_once_after_invalid_json(monkeypatch) -> None:
    client = OpenAICompatibleReviewLlm(
        {
            "api_base": "https://api.deepseek.com",
            "api_key": "test-key",
            "model": "test-model",
            "provider": "deepseek",
            "wire_api": "chat_completions",
        }
    )
    valid_response = {
        "issues": [
            {
                "source_file_id": "FILE-1",
                "source_file_name": "report.docx",
                "category": "data_inconsistency",
                "risk_level": "high",
                "location": {"paragraph": 1},
                "description": "value mismatch",
                "evidence_summaries": ["evidence"],
                "confidence": 0.9,
                "rule_id": "llm.review.v1",
            }
        ]
    }
    responses = iter(
        [
            {"choices": [{"message": {"content": '{"issues": ['}}]},
            {
                "choices": [
                    {"message": {"content": json.dumps(valid_response)}}
                ]
            },
        ]
    )
    calls = []

    def fake_post(_url, _payload):
        calls.append(True)
        return next(responses)

    monkeypatch.setattr(client, "_post_json", fake_post)

    findings = client.review_batches([_review_batch()])

    assert len(calls) == 2
    assert len(findings) == 1


def test_review_llm_reports_batch_and_network_retry_progress(monkeypatch) -> None:
    client = OpenAICompatibleReviewLlm(
        {
            "api_base": "https://api.deepseek.com",
            "api_key": "test-key",
            "model": "test-model",
            "provider": "deepseek",
            "wire_api": "chat_completions",
        }
    )
    valid_response = {"issues": []}
    responses = iter(
        [
            ReviewNetworkError("connection interrupted"),
            {"choices": [{"message": {"content": json.dumps(valid_response)}}]},
            {"choices": [{"message": {"content": json.dumps(valid_response)}}]},
        ]
    )

    def fake_post(_url, _payload):
        response = next(responses)
        if isinstance(response, Exception):
            raise response
        return response

    monkeypatch.setattr(client, "_post_json", fake_post)
    progress: list[dict[str, object]] = []
    second_batch = _review_batch().model_copy(
        update={"batch_id": "BATCH-0002"}
    )

    client.review_batches(
        [_review_batch(), second_batch],
        progress_callback=lambda payload: progress.append(dict(payload)),
    )

    assert [
        (
            item["state"],
            item["batch_index"],
            item["batch_total"],
            item["attempt"],
            item["attempt_total"],
        )
        for item in progress
    ] == [
        ("requesting", 1, 2, 1, 3),
        ("retrying", 1, 2, 2, 3),
        ("completed", 1, 2, 2, 3),
        ("requesting", 2, 2, 1, 3),
        ("completed", 2, 2, 1, 3),
    ]


def test_review_llm_parses_structured_advice(monkeypatch) -> None:
    client = OpenAICompatibleReviewLlm(
        {
            "api_base": "https://example.invalid",
            "api_key": "test-key",
            "model": "test-model",
            "wire_api": "chat",
        }
    )
    monkeypatch.setattr(
        client,
        "_post_json",
        lambda _url, _payload: {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "explanation": "核对金额",
                                "checks": ["检查测算表"],
                                "suggested_revision": "建议例文",
                            }
                        )
                    }
                }
            ]
        },
    )
    issue = ReviewIssue(
        issue_id="ISSUE-1",
        fingerprint="fingerprint",
        source_file_id="FILE-1",
        source_file_name="report.docx",
        category="data",
        risk_level=RiskLevel.HIGH,
        status=IssueStatus.NEW,
        location=IssueLocation(paragraph=1),
        description="value mismatch",
        confidence=0.9,
        first_seen_round=1,
        last_seen_round=1,
    )

    result = client.generate_advice(
        AdviceRequest(project_id="PROJECT-1", issue=issue)
    )

    assert result.issue_id == "ISSUE-1"
    assert result.checks == ["检查测算表"]


def test_review_llm_continues_issue_scoped_conversation(monkeypatch) -> None:
    client = OpenAICompatibleReviewLlm(
        {
            "api_base": "https://example.invalid",
            "api_key": "test-key",
            "model": "test-model",
            "wire_api": "chat",
        }
    )
    captured = {}

    def fake_post(_url, payload):
        captured.update(payload)
        return {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "reply": "建议先核对评估值，再统一修改报告结论。"
                            }
                        )
                    }
                }
            ]
        }

    monkeypatch.setattr(client, "_post_json", fake_post)
    review_issue = ReviewIssue(
        issue_id="ISSUE-1",
        fingerprint="fingerprint",
        source_file_id="FILE-1",
        source_file_name="report.docx",
        category="data",
        risk_level=RiskLevel.HIGH,
        status=IssueStatus.NEW,
        location=IssueLocation(paragraph=1),
        description="value mismatch",
        confidence=0.9,
        first_seen_round=1,
        last_seen_round=1,
    )

    result = client.continue_conversation(
        ConversationTurnRequest(
            project_id="PROJECT-1",
            issue=review_issue,
            advice=AdviceResult(
                issue_id="ISSUE-1",
                explanation="先核对金额",
            ),
            messages=[
                ConversationMessage(
                    role="user",
                    content="先核对什么？",
                    created_at="2026-07-31T00:00:00+00:00",
                ),
                ConversationMessage(
                    role="assistant",
                    content="先核对原始凭证。",
                    created_at="2026-07-31T00:00:01+00:00",
                ),
            ],
            user_message="然后如何修改？",
        )
    )

    prompt = captured["messages"][1]["content"]
    assert result.reply == "建议先核对评估值，再统一修改报告结论。"
    assert "先核对原始凭证" in prompt
    assert "然后如何修改" in prompt
    assert "不得修改文件" in prompt
    assert "最终汇总审核报告" in prompt


def test_deepseek_uses_official_chat_endpoint_and_json_output() -> None:
    client = OpenAICompatibleReviewLlm(
        {
            "api_base": "https://api.deepseek.com",
            "api_key": "deepseek-key",
            "model": "deepseek-v4-pro",
            "provider": "deepseek",
            "wire_api": "chat_completions",
        }
    )

    assert client._endpoint() == "https://api.deepseek.com/chat/completions"
    assert client._generic_request_payload("review")["response_format"] == {
        "type": "json_object"
    }


def test_openai_compatible_base_with_v1_is_not_duplicated() -> None:
    client = OpenAICompatibleReviewLlm(
        {
            "api_base": "https://api.example.com/v1",
            "api_key": "test-key",
            "model": "test-model",
            "provider": "openai-compatible",
            "wire_api": "responses",
        }
    )

    assert client._endpoint() == "https://api.example.com/v1/responses"


def _review_batch() -> ReviewBatch:
    return ReviewBatch(
        batch_id="BATCH-0001",
        character_count=4,
        chunks=[
            DocumentChunk(
                chunk_id="chunk-1",
                source_file_id="FILE-1",
                source_file_name="report.docx",
                role=FileRole.MAIN_REPORT,
                text="text",
                location=IssueLocation(paragraph=1),
            )
        ],
    )
