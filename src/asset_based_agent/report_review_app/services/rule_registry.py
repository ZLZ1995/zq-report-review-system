"""Extensible deterministic read-only review rule registry."""

from __future__ import annotations

import re
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

from asset_based_agent.reporting.valuation_report_structure import (
    REQUIRED_BODY_HEADINGS,
    normalize_heading,
)

from ..domain.enums import FileRole, RiskLevel
from ..domain.models import IssueLocation
from .document_extraction_service import DocumentChunk, ExtractedDocument


class IssueCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_file_id: str
    source_file_name: str
    category: str
    risk_level: RiskLevel
    location: IssueLocation
    original_text: str = ""
    description: str
    evidence_summaries: list[str] = Field(default_factory=list)
    recommendation: str = ""
    confidence: float = Field(ge=0.0, le=1.0)
    rule_id: str = ""
    allow_reference_source: bool = False
    requires_verification: bool = False
    claim_type: str | None = None
    target_sheet: str | None = None
    target_rows: list[int] = Field(default_factory=list)
    requires_global_search: bool = False
    tax_evidence: dict[str, str] = Field(default_factory=dict)
    occurrences: list[IssueLocation] = Field(default_factory=list)


class ReviewRule(Protocol):
    rule_id: str

    def evaluate(self, documents: list[ExtractedDocument]) -> list[IssueCandidate]:
        ...


class RuleRegistry:
    def __init__(self, rules: list[ReviewRule] | None = None) -> None:
        self._rules: dict[str, ReviewRule] = {}
        for rule in rules or []:
            self.register(rule)

    def register(self, rule: ReviewRule) -> None:
        if rule.rule_id in self._rules:
            raise ValueError(f"duplicate review rule: {rule.rule_id}")
        self._rules[rule.rule_id] = rule

    def evaluate(self, documents: list[ExtractedDocument]) -> list[IssueCandidate]:
        findings: list[IssueCandidate] = []
        for rule in self._rules.values():
            findings.extend(rule.evaluate(documents))
        return findings


class RepeatedPunctuationRule:
    rule_id = "native_review.repeated_punctuation.v1"

    def evaluate(self, documents: list[ExtractedDocument]) -> list[IssueCandidate]:
        findings: list[IssueCandidate] = []
        for document in documents:
            if document.source_file.extension == ".pdf":
                continue
            for chunk in document.chunks:
                if "。。" not in chunk.text and "，，" not in chunk.text:
                    continue
                findings.append(
                    IssueCandidate(
                        source_file_id=chunk.source_file_id,
                        source_file_name=chunk.source_file_name,
                        category="text_quality",
                        risk_level=RiskLevel.LOW,
                        location=chunk.location,
                        original_text=chunk.text,
                        description="发现连续中文标点，请核对是否为文字错误。",
                        recommendation="删除重复标点，并复核修改后语句是否完整。",
                        confidence=0.99,
                        rule_id=self.rule_id,
                    )
                )
        return findings


class BrokenSummaryFormulaRule:
    rule_id = "native_review.broken_summary_formula.v1"

    def evaluate(self, documents: list[ExtractedDocument]) -> list[IssueCandidate]:
        findings: list[IssueCandidate] = []
        for document in documents:
            if document.source_file.role != FileRole.CALCULATION_WORKBOOK:
                continue
            for chunk in document.chunks:
                if chunk.reference_only:
                    continue
                if "#REF!" not in chunk.text:
                    continue
                findings.append(
                    IssueCandidate(
                        source_file_id=chunk.source_file_id,
                        source_file_name=chunk.source_file_name,
                        category="broken_formula_reference",
                        risk_level=RiskLevel.HIGH,
                        location=chunk.location,
                        original_text=chunk.text,
                        description="可见工作表的公式中存在无效引用（#REF!）。",
                        evidence_summaries=[
                            "该单元格位于参与审核的可见工作表中。"
                        ],
                        recommendation="核对缺失的工作表或单元格引用，并重新计算汇总结果。",
                        confidence=1.0,
                        rule_id=self.rule_id,
                    )
                )
        return findings


class AttachmentCompletenessRule:
    rule_id = "native_review.attachment_completeness.v1"

    def evaluate(self, documents: list[ExtractedDocument]) -> list[IssueCandidate]:
        findings: list[IssueCandidate] = []
        for document in documents:
            if document.source_file.extension != ".docx":
                continue
            ordered = sorted(
                (
                    chunk
                    for chunk in document.chunks
                    if chunk.story_type == "body" and chunk.sequence is not None
                ),
                key=lambda chunk: chunk.sequence or 0,
            )
            attachment_headings = [
                chunk
                for chunk in ordered
                if chunk.text.strip().startswith("附件")
                and _is_heading_chunk(chunk)
            ]
            for heading in attachment_headings:
                following = [
                    chunk
                    for chunk in ordered
                    if (chunk.sequence or 0) > (heading.sequence or 0)
                ]
                if following:
                    continue
                findings.append(
                    IssueCandidate(
                        source_file_id=heading.source_file_id,
                        source_file_name=heading.source_file_name,
                        category="missing_attachment_content",
                        risk_level=RiskLevel.HIGH,
                        location=heading.location,
                        original_text=heading.text,
                        description="文档列示了附件标题，但附件标题后没有有效内容。",
                        recommendation="核对附件是否遗漏，并补充对应附件内容。",
                        confidence=1.0,
                        rule_id=self.rule_id,
                    )
                )
        return findings


class ExistingReportHeadingRule:
    """Read-only adapter around the repository's formal report heading contract."""

    rule_id = "existing_adapter.formal_report_headings.v1"

    def evaluate(self, documents: list[ExtractedDocument]) -> list[IssueCandidate]:
        findings: list[IssueCandidate] = []
        required = {
            _semantic_heading(heading): heading for heading in REQUIRED_BODY_HEADINGS
        }
        for document in documents:
            if document.source_file.role != FileRole.MAIN_REPORT:
                continue
            observed = {
                _semantic_heading(chunk.text)
                for chunk in document.chunks
                if len(chunk.text) <= 80
                and _is_heading_chunk(chunk)
            }
            if "委托人、产权持有人及其他资产评估报告使用人" in observed:
                observed.add("委托人、被评估单位及其他资产评估报告使用人")
            missing = [
                display for normalized, display in required.items() if normalized not in observed
            ]
            for heading in missing:
                findings.append(
                    IssueCandidate(
                        source_file_id=document.source_file.file_id,
                        source_file_name=document.source_file.original_name,
                        category="missing_required_heading",
                        risk_level=RiskLevel.HIGH,
                        location=IssueLocation(chapter=heading),
                        description=f"正式评估报告缺少规定的一级标题：{heading}",
                        recommendation="核对报告正文一级目录结构，补充或恢复缺失标题。",
                        confidence=0.99,
                        rule_id=self.rule_id,
                    )
                )
        return findings


_MAJOR_HEADING_PREFIX = re.compile(r"^[一二三四五六七八九十百]+[、，,.．]\s*")


def _semantic_heading(text: str) -> str:
    return _MAJOR_HEADING_PREFIX.sub("", normalize_heading(text))


def _is_heading_chunk(chunk: DocumentChunk) -> bool:
    if chunk.is_toc_entry or chunk.story_type != "body":
        return False
    if chunk.style_name is None and chunk.outline_level is None:
        return True
    style_name = (chunk.style_name or "").lower()
    return (
        "heading" in style_name
        or "标题" in style_name
        or chunk.outline_level is not None
    )


class TemplatePlaceholderRule:
    rule_id = "existing_adapter.template_placeholder.v1"
    _pattern = re.compile(
        r"(?:XX+|××+|某某)(?:公司|集团|项目)"
        r"|第\s*[XＸ]{3,}\s*号|待填写|待补充|示例文本",
        re.IGNORECASE,
    )

    def evaluate(self, documents: list[ExtractedDocument]) -> list[IssueCandidate]:
        findings: list[IssueCandidate] = []
        for document in documents:
            if document.source_file.extension == ".pdf":
                continue
            for chunk in document.chunks:
                match = self._pattern.search(chunk.text)
                if match is None:
                    continue
                findings.append(
                    IssueCandidate(
                        source_file_id=chunk.source_file_id,
                        source_file_name=chunk.source_file_name,
                        category="template_residue",
                        risk_level=RiskLevel.HIGH,
                        location=chunk.location,
                        original_text=chunk.text,
                        description=f"发现疑似模板占位内容：{match.group(0)}",
                        recommendation="结合本项目实际信息核对并清理模板占位内容。",
                        confidence=0.96,
                        rule_id=self.rule_id,
                    )
                )
        return findings


class ScoreConservationRule:
    rule_id = "existing_adapter.score_conservation.v1"
    _number = re.compile(r"[-+]?\d+(?:\.\d+)?%?")

    def evaluate(self, documents: list[ExtractedDocument]) -> list[IssueCandidate]:
        findings: list[IssueCandidate] = []
        for document in documents:
            if document.source_file.role != FileRole.CALCULATION_WORKBOOK:
                continue
            for chunk in document.chunks:
                text = chunk.text
                if not any(marker in text for marker in ("总分", "权重合计", "权重总计")):
                    continue
                numbers = self._number.findall(text)
                if not numbers:
                    continue
                raw = numbers[-1]
                value = float(raw.rstrip("%"))
                expected = 100.0 if ("总分" in text or raw.endswith("%")) else 1.0
                if abs(value - expected) <= 1e-6:
                    continue
                findings.append(
                    IssueCandidate(
                        source_file_id=chunk.source_file_id,
                        source_file_name=chunk.source_file_name,
                        category="score_or_weight_not_conserved",
                        risk_level=RiskLevel.HIGH,
                        location=chunk.location,
                        original_text=text,
                        description=f"评分或权重合计为{value:g}，未满足{expected:g}的守恒要求。",
                        recommendation="核对同层级评分或权重，并采用守恒调整。",
                        confidence=0.92,
                        rule_id=self.rule_id,
                    )
                )
        return findings


class ConclusionAmountConsistencyRule:
    rule_id = "native_review.conclusion_amount_consistency.v1"
    _amount = re.compile(r"(?<!\d)(\d{1,3}(?:,\d{3})*(?:\.\d+)?|\d+\.\d+)(?!\d)")

    def evaluate(self, documents: list[ExtractedDocument]) -> list[IssueCandidate]:
        report_candidates = self._amount_candidates(
            documents,
            {FileRole.MAIN_REPORT, FileRole.VALUATION_EXPLANATION},
        )
        workbook_candidates = self._amount_candidates(
            documents,
            {FileRole.CALCULATION_WORKBOOK},
        )
        if len(report_candidates) != 1 or len(workbook_candidates) != 1:
            return []
        report_chunk, report_value = report_candidates[0]
        workbook_chunk, workbook_value = workbook_candidates[0]
        if abs(report_value - workbook_value) <= 1e-6:
            return []
        return [
            IssueCandidate(
                source_file_id=report_chunk.source_file_id,
                source_file_name=report_chunk.source_file_name,
                category="conclusion_amount_mismatch",
                risk_level=RiskLevel.CRITICAL,
                location=report_chunk.location,
                original_text=report_chunk.text,
                description=(
                    f"报告结论金额{report_value:g}与测算表结论金额"
                    f"{workbook_value:g}不一致。"
                ),
                evidence_summaries=[workbook_chunk.text],
                recommendation="核对金额单位、公式计算结果和报告最终结论。",
                confidence=0.9,
                rule_id=self.rule_id,
            )
        ]

    def _amount_candidates(
        self,
        documents: list[ExtractedDocument],
        roles: set[FileRole],
    ) -> list[tuple[DocumentChunk, float]]:
        candidates: list[tuple[DocumentChunk, float]] = []
        for document in documents:
            if document.source_file.role not in roles:
                continue
            for chunk in document.chunks:
                markers = ("评估结论", "评估结果", "评估值")
                marker_positions = [
                    (chunk.text.find(marker), marker)
                    for marker in markers
                    if marker in chunk.text
                ]
                if not marker_positions:
                    continue
                position, marker = min(marker_positions, key=lambda item: item[0])
                value_text = chunk.text[position + len(marker) :]
                numbers = self._amount.findall(value_text)
                if numbers:
                    candidates.append((chunk, float(numbers[-1].replace(",", ""))))
        return candidates


def default_rule_registry() -> RuleRegistry:
    return RuleRegistry(
        [
            ExistingReportHeadingRule(),
            BrokenSummaryFormulaRule(),
            AttachmentCompletenessRule(),
            TemplatePlaceholderRule(),
            ScoreConservationRule(),
            ConclusionAmountConsistencyRule(),
            RepeatedPunctuationRule(),
        ]
    )
