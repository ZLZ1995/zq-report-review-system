"""Structured LLM review interface and OpenAI-compatible implementation."""

from __future__ import annotations

import json
from http.client import IncompleteRead, RemoteDisconnected
from collections.abc import Callable
from typing import Any, Protocol
from urllib import request
from urllib.error import HTTPError, URLError

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from asset_based_agent.llm.config import load_model_config

from ..domain.enums import RiskLevel
from .agent_gateway import (
    AdviceRequest,
    AdviceResult,
    ConversationTurnRequest,
    ConversationTurnResult,
)
from .privacy_filter import ReviewBatch
from .rule_registry import IssueCandidate


class LlmBatchResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    issues: list[IssueCandidate] = Field(default_factory=list)


class ReviewLlm(Protocol):
    def review_batches(
        self,
        batches: list[ReviewBatch],
        progress_callback: Callable[[dict[str, object]], None] | None = None,
    ) -> list[IssueCandidate]:
        ...


class ReviewNetworkError(RuntimeError):
    pass


class ReviewResponseSchemaError(RuntimeError):
    """The model responded, but its JSON did not match the review contract."""


class OpenAICompatibleReviewLlm:
    def __init__(self, config: dict[str, object] | None = None) -> None:
        self.config = config or load_model_config()

    def review_batches(
        self,
        batches: list[ReviewBatch],
        progress_callback: Callable[[dict[str, object]], None] | None = None,
    ) -> list[IssueCandidate]:
        if not self.config.get("api_key") or not self.config.get("api_base"):
            raise RuntimeError("LLM configuration is incomplete")
        findings: list[IssueCandidate] = []
        batch_total = len(batches)
        attempt_total = 3
        for batch_index, batch in enumerate(batches, start=1):
            for attempt in range(1, attempt_total + 1):
                _emit_review_progress(
                    progress_callback,
                    state="requesting" if attempt == 1 else "retrying",
                    batch_index=batch_index,
                    batch_total=batch_total,
                    attempt=attempt,
                    attempt_total=attempt_total,
                )
                try:
                    findings.extend(self._review_batch(batch))
                    _emit_review_progress(
                        progress_callback,
                        state="completed",
                        batch_index=batch_index,
                        batch_total=batch_total,
                        attempt=attempt,
                        attempt_total=attempt_total,
                    )
                    break
                except (ReviewResponseSchemaError, ReviewNetworkError):
                    if attempt == attempt_total:
                        raise
        return findings

    def generate_advice(self, request_payload: AdviceRequest) -> AdviceResult:
        if not self.config.get("api_key") or not self.config.get("api_base"):
            raise RuntimeError("LLM configuration is incomplete")
        prompt = _build_advice_prompt(request_payload)
        response = self._post_json(
            self._endpoint(),
            self._generic_request_payload(prompt),
        )
        text = self._response_text(response)
        try:
            payload = json.loads(_strip_code_fence(text))
            payload.setdefault("issue_id", request_payload.issue.issue_id)
            return AdviceResult.model_validate(payload)
        except (json.JSONDecodeError, ValidationError) as exc:
            raise RuntimeError(f"LLM advice response failed schema validation: {exc}") from exc

    def continue_conversation(
        self,
        request_payload: ConversationTurnRequest,
    ) -> ConversationTurnResult:
        if not self.config.get("api_key") or not self.config.get("api_base"):
            raise RuntimeError("LLM configuration is incomplete")
        response = self._post_json(
            self._endpoint(),
            self._generic_request_payload(
                _build_conversation_prompt(request_payload)
            ),
        )
        text = self._response_text(response)
        try:
            payload = json.loads(_strip_code_fence(text))
            return ConversationTurnResult.model_validate(payload)
        except (json.JSONDecodeError, ValidationError, TypeError) as exc:
            raise RuntimeError(
                f"LLM conversation response failed schema validation: {exc}"
            ) from exc

    def _review_batch(self, batch: ReviewBatch) -> list[IssueCandidate]:
        payload = self._request_payload(batch)
        url = self._endpoint()
        response = self._post_json(url, payload)
        text = self._response_text(response)
        try:
            parsed = json.loads(_strip_code_fence(text))
            normalized = _normalize_review_response(parsed)
            return LlmBatchResponse.model_validate(normalized).issues
        except (json.JSONDecodeError, ValidationError, ValueError, TypeError) as exc:
            detail = _schema_error_detail(exc)
            raise ReviewResponseSchemaError(
                f"LLM review response failed schema validation: {detail}"
            ) from exc

    def _request_payload(self, batch: ReviewBatch) -> dict[str, object]:
        prompt = _build_review_prompt(batch)
        return self._generic_request_payload(prompt)

    def _generic_request_payload(self, prompt: str) -> dict[str, object]:
        model = str(self.config.get("model") or "gpt-4.1")
        if self.config.get("wire_api") == "responses":
            return {
                "model": model,
                "input": [
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
            }
        payload: dict[str, object] = {
            "model": model,
            "messages": [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.1,
        }
        if self.config.get("provider") == "deepseek":
            payload["response_format"] = {"type": "json_object"}
        return payload

    def _endpoint(self) -> str:
        base = str(self.config["api_base"]).rstrip("/")
        if self.config.get("provider") == "deepseek":
            return base + "/chat/completions"
        if self.config.get("wire_api") == "responses":
            return _versioned_endpoint(base, "responses")
        return _versioned_endpoint(base, "chat/completions")

    @staticmethod
    def _response_text(payload: dict[str, Any]) -> str:
        if payload.get("choices"):
            choices = payload["choices"]
            return str(choices[0]["message"]["content"])
        parts: list[str] = []
        for item in payload.get("output", []):
            for content in item.get("content", []):
                if content.get("text"):
                    parts.append(str(content["text"]))
        return "\n".join(parts)

    def _post_json(self, url: str, payload: dict[str, object]) -> dict[str, object]:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = request.Request(
            url,
            data=body,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.config['api_key']}",
            },
            method="POST",
        )
        try:
            with request.urlopen(req, timeout=60) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"LLM HTTP {exc.code}: {detail}") from exc
        except (
            URLError,
            TimeoutError,
            IncompleteRead,
            RemoteDisconnected,
            ConnectionError,
        ) as exc:
            raise ReviewNetworkError(f"LLM network request failed: {exc}") from exc


class NoOpReviewLlm:
    """Explicit local fallback that produces no model findings."""

    def review_batches(
        self,
        batches: list[ReviewBatch],
        progress_callback: Callable[[dict[str, object]], None] | None = None,
    ) -> list[IssueCandidate]:
        return []


def _emit_review_progress(
    callback: Callable[[dict[str, object]], None] | None,
    **payload: object,
) -> None:
    if callback is not None:
        callback(payload)


_SYSTEM_PROMPT = (
    "你是中国资产评估报告只读审核模块。只能指出问题并返回结构化 JSON，"
    "不得修改文件，不得编造文件、位置、金额或结论。"
)


def _build_review_prompt(batch: ReviewBatch) -> str:
    chunks = [
        {
            "chunk_id": chunk.chunk_id,
            "source_file_id": chunk.source_file_id,
            "source_file_name": chunk.source_file_name,
            "role": chunk.role.value,
            "reference_only": chunk.reference_only,
            "location": chunk.location.model_dump(mode="json"),
            "text": chunk.text,
        }
        for chunk in batch.chunks
    ]
    schema_example = {
        "issues": [
            {
                "source_file_id": "FILE-ID",
                "source_file_name": "report.docx",
                "category": "data_inconsistency",
                "risk_level": RiskLevel.HIGH.value,
                "location": {"chapter": None, "page": None, "paragraph": 1},
                "original_text": "text",
                "description": "problem",
                "evidence_summaries": ["第1段：支持该问题判断的证据摘要"],
                "recommendation": "advice",
                "confidence": 0.9,
                "rule_id": "llm.review.v1",
                "requires_verification": False,
                "claim_type": None,
                "target_sheet": None,
                "target_rows": [],
                "requires_global_search": False,
                "tax_evidence": {},
            }
        ]
    }
    return (
        "审核以下已在本地提取的文本片段。reference_only=true 的片段"
        "（仅包括允许上送的参考文档）只能作为证据，不得成为问题来源。"
        "隐藏或 veryHidden 工作表已由本地门禁排除，禁止根据隐藏表内容提出问题。"
        "只返回 JSON，不要返回 Markdown。"
        "evidence_summaries 必须是字符串数组，每一项只能是字符串；"
        "位置编号应直接写入字符串，禁止返回 content、paragraph 等嵌套对象。\n"
        "如果结论依赖缺失的税务身份、报价口径、抵扣资格或其他材料，"
        "必须设置 requires_verification=true，不得表述为已确认错误。"
        "不得仅因当前批次没有出现某行或某段，就断言其在完整文件中不存在。\n"
        "凡声称行不存在，必须设置 claim_type=missing_row、target_sheet、"
        "target_rows 和 requires_global_search=true，供本地全局索引验证。"
        "税务错误只有在 tax_evidence 中完整提供基准日纳税人身份、供应商身份、"
        "报价含税口径、报价税率、进项税抵扣资格和评估取价口径时才能确认；"
        "否则必须设置 requires_verification=true。"
        f"输出结构示例：{json.dumps(schema_example, ensure_ascii=False)}\n"
        f"片段：{json.dumps(chunks, ensure_ascii=False)}"
    )


def _build_advice_prompt(advice_request: AdviceRequest) -> str:
    issue = advice_request.issue
    payload = {
        "issue_id": issue.issue_id,
        "file": issue.source_file_name,
        "category": issue.category,
        "risk_level": issue.risk_level.value,
        "location": issue.location.model_dump(mode="json"),
        "original_text": issue.original_text,
        "description": issue.description,
        "evidence": [item.model_dump(mode="json") for item in issue.evidence],
        "context_fragments": advice_request.context_fragments,
    }
    schema = {
        "issue_id": issue.issue_id,
        "explanation": "问题原因和处理方向",
        "checks": ["需要核对的事项"],
        "suggested_revision": "必要时提供建议例文",
    }
    return (
        "只针对当前问题提出解决方案，不得修改文件，不得扩展到其他问题。"
        "只返回JSON，不要返回Markdown。\n"
        f"输出结构：{json.dumps(schema, ensure_ascii=False)}\n"
        f"问题：{json.dumps(payload, ensure_ascii=False)}"
    )


def _build_conversation_prompt(request_payload: ConversationTurnRequest) -> str:
    issue = request_payload.issue
    payload = {
        "issue": {
            "issue_id": issue.issue_id,
            "file": issue.source_file_name,
            "category": issue.category,
            "risk_level": issue.risk_level.value,
            "location": issue.location.model_dump(mode="json"),
            "original_text": issue.original_text,
            "description": issue.description,
            "evidence": [item.model_dump(mode="json") for item in issue.evidence],
        },
        "initial_advice": (
            request_payload.advice.model_dump(mode="json")
            if request_payload.advice is not None
            else None
        ),
        "conversation": [
            {
                "role": message.role,
                "content": message.content,
            }
            for message in request_payload.messages
        ],
        "user_message": request_payload.user_message,
    }
    return (
        "你正在与用户围绕一个已确认的审核问题进行多轮讨论。"
        "只讨论当前问题，帮助用户逐步形成可执行的修改方案；"
        "不得扩展到其他问题，不得修改文件，不得声称已完成修改。"
        "本次对话及最终修改方案不得写入最终汇总审核报告。"
        "只返回JSON对象，格式为："
        '{"reply":"本轮面向用户的答复"}。'
        "答复可以使用简短分点，但不要包含JSON以外的字段。\n"
        f"对话上下文：{json.dumps(payload, ensure_ascii=False)}"
    )


def _strip_code_fence(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if lines:
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        return "\n".join(lines).strip()
    return stripped


def _normalize_review_response(payload: object) -> dict[str, object]:
    if not isinstance(payload, dict):
        raise ValueError("response must be a JSON object")
    issues = payload.get("issues", [])
    if issues is None:
        issues = []
    if not isinstance(issues, list):
        raise ValueError("issues must be an array")

    normalized_issues: list[dict[str, object]] = []
    for issue_index, issue in enumerate(issues):
        if not isinstance(issue, dict):
            raise ValueError(f"issues.{issue_index} must be an object")
        normalized_issue = dict(issue)
        normalized_issue["evidence_summaries"] = _normalize_evidence_summaries(
            issue.get("evidence_summaries"),
            path=f"issues.{issue_index}.evidence_summaries",
        )
        normalized_issues.append(normalized_issue)

    normalized = dict(payload)
    normalized["issues"] = normalized_issues
    return normalized


def _normalize_evidence_summaries(value: object, *, path: str) -> list[str]:
    if value is None:
        return []
    items = [value] if isinstance(value, str) else value
    if not isinstance(items, list):
        raise ValueError(f"{path} must be an array of strings")

    normalized: list[str] = []
    for item_index, item in enumerate(items):
        if isinstance(item, str):
            text = item.strip()
        elif isinstance(item, dict):
            text = _evidence_text_from_object(item, path=f"{path}.{item_index}")
        else:
            raise ValueError(
                f"{path}.{item_index} must be a string or supported evidence object"
            )
        if text:
            normalized.append(text)
    return normalized


def _evidence_text_from_object(item: dict[object, object], *, path: str) -> str:
    content = ""
    for key in ("content", "summary", "text"):
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            content = value.strip()
            break
    if not content:
        raise ValueError(
            f"{path} must contain a non-empty content, summary, or text string"
        )

    location = ""
    if item.get("paragraph") not in (None, ""):
        location = f"第{item['paragraph']}段"
    elif item.get("page") not in (None, ""):
        location = f"第{item['page']}页"
    elif item.get("chapter") not in (None, ""):
        location = f"章节{item['chapter']}"
    return f"{location}：{content}" if location else content


def _schema_error_detail(exc: Exception) -> str:
    if isinstance(exc, ValidationError):
        details = []
        for error in exc.errors(include_url=False, include_input=False):
            location = ".".join(str(part) for part in error.get("loc", ()))
            message = str(error.get("msg") or "invalid value")
            details.append(f"{location}: {message}" if location else message)
        return "; ".join(details)
    if isinstance(exc, json.JSONDecodeError):
        return f"invalid JSON at line {exc.lineno}, column {exc.colno}"
    return str(exc)


def _versioned_endpoint(api_base: str, path: str) -> str:
    if api_base.lower().endswith("/v1"):
        return f"{api_base}/{path}"
    return f"{api_base}/v1/{path}"
