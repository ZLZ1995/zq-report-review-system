from __future__ import annotations

from asset_based_agent.report_review_app.domain.enums import FileRole
from asset_based_agent.report_review_app.domain.models import IssueLocation, SourceFile
from asset_based_agent.report_review_app.services.document_extraction_service import (
    DocumentChunk,
    ExtractedDocument,
)
from asset_based_agent.report_review_app.services.privacy_filter import PrivacyChunkSelector
from asset_based_agent.report_review_app.services.rule_registry import (
    AttachmentCompletenessRule,
    BrokenSummaryFormulaRule,
    ConclusionAmountConsistencyRule,
    ExistingReportHeadingRule,
    RepeatedPunctuationRule,
    ScoreConservationRule,
    TemplatePlaceholderRule,
)
from asset_based_agent.reporting.valuation_report_structure import REQUIRED_BODY_HEADINGS


def document(
    texts: list[str],
    extension: str = ".docx",
    *,
    role: FileRole = FileRole.MAIN_REPORT,
    file_id: str = "FILE-1",
) -> ExtractedDocument:
    source = SourceFile(
        file_id=file_id,
        original_name=f"source{extension}",
        extension=extension,
        sha256="hash",
        size_bytes=1,
        role=role,
        round_number=1,
        original_path="source",
    )
    return ExtractedDocument(
        source_file=source,
        extraction_mode="test",
        chunks=[
            DocumentChunk(
                chunk_id=f"chunk-{index}",
                source_file_id=source.file_id,
                source_file_name=source.original_name,
                role=source.role,
                text=text,
                location=IssueLocation(paragraph=index),
                reference_only=extension == ".pdf",
            )
            for index, text in enumerate(texts, start=1)
        ],
    )


def test_privacy_selector_bounds_each_batch() -> None:
    batches = PrivacyChunkSelector(max_batch_characters=500).build_batches(
        [document(["A" * 300, "B" * 300, "C" * 300])]
    )

    assert len(batches) == 3
    assert all(batch.character_count <= 500 for batch in batches)


def test_privacy_selector_never_sends_hidden_workbook_chunks_to_llm() -> None:
    workbook = document(
        ["可见电子设备", "隐藏模板数据"],
        extension=".xlsx",
        role=FileRole.CALCULATION_WORKBOOK,
    )
    workbook.chunks[1].reference_only = True
    workbook.chunks[1].location = IssueLocation(table="其他应收款", cell="row:16")

    batches = PrivacyChunkSelector(max_batch_characters=500).build_batches([workbook])

    assert [
        chunk.text
        for batch in batches
        for chunk in batch.chunks
    ] == ["可见电子设备"]


def test_privacy_selector_keeps_pdf_reference_chunks_for_llm_context() -> None:
    pdf = document(
        ["PDF参考依据"],
        extension=".pdf",
        role=FileRole.REFERENCE_DOCUMENT,
    )

    batches = PrivacyChunkSelector(max_batch_characters=500).build_batches([pdf])

    assert [chunk.text for batch in batches for chunk in batch.chunks] == [
        "PDF参考依据"
    ]


def test_repeated_punctuation_rule_ignores_pdf_reference() -> None:
    rule = RepeatedPunctuationRule()

    report_findings = rule.evaluate([document(["存在。。重复标点"])])
    pdf_findings = rule.evaluate([document(["存在。。重复标点"], extension=".pdf")])

    assert len(report_findings) == 1
    assert pdf_findings == []


def test_existing_heading_adapter_uses_repository_required_headings() -> None:
    rule = ExistingReportHeadingRule()

    complete = rule.evaluate([document(list(REQUIRED_BODY_HEADINGS))])
    missing = rule.evaluate([document(list(REQUIRED_BODY_HEADINGS[1:]))])

    assert complete == []
    assert len(missing) == 1
    assert missing[0].category == "missing_required_heading"


def test_existing_heading_adapter_accepts_word_auto_numbered_heading_text() -> None:
    rule = ExistingReportHeadingRule()
    auto_numbered_text = [
        heading.split("、", 1)[-1]
        for heading in REQUIRED_BODY_HEADINGS
    ]
    auto_numbered_text[0] = "委托人、产权持有人及其他资产评估报告使用人"

    findings = rule.evaluate([document(auto_numbered_text)])

    assert findings == []


def test_existing_heading_adapter_does_not_treat_normal_body_text_as_heading() -> None:
    doc = document(
        [heading.split("、", 1)[-1] for heading in REQUIRED_BODY_HEADINGS]
    )
    for chunk in doc.chunks:
        chunk.style_name = "Normal"

    findings = ExistingReportHeadingRule().evaluate([doc])

    assert len(findings) == len(REQUIRED_BODY_HEADINGS)


def test_broken_formula_in_visible_summary_is_reported() -> None:
    doc = document(
        ["B1==#REF!-#REF!"],
        extension=".xlsx",
        role=FileRole.CALCULATION_WORKBOOK,
    )
    doc.chunks[0].reference_only = False
    doc.chunks[0].summary_impact = True
    doc.chunks[0].location = IssueLocation(table="汇总表", cell="row:1")

    findings = BrokenSummaryFormulaRule().evaluate([doc])

    assert len(findings) == 1
    assert findings[0].allow_reference_source is False


def test_broken_formula_rule_never_audits_hidden_workbook_chunks() -> None:
    doc = document(
        ["B1==#REF!-#REF!"],
        extension=".xlsx",
        role=FileRole.CALCULATION_WORKBOOK,
    )
    doc.chunks[0].reference_only = True
    doc.chunks[0].summary_impact = True
    doc.chunks[0].location = IssueLocation(table="隐藏数据", cell="row:1")

    findings = BrokenSummaryFormulaRule().evaluate([doc])

    assert findings == []


def test_attachment_heading_without_following_content_is_reported() -> None:
    doc = document(["正文", "附件：有关事项说明"])
    doc.chunks[0].sequence = 1
    doc.chunks[1].sequence = 2
    doc.chunks[1].style_name = "Heading 1"

    findings = AttachmentCompletenessRule().evaluate([doc])

    assert len(findings) == 1
    assert findings[0].category == "missing_attachment_content"


def test_template_placeholder_rule_finds_project_residue() -> None:
    findings = TemplatePlaceholderRule().evaluate(
        [document(["XX公司股东全部权益价值评估项目"])]
    )

    assert len(findings) == 1
    assert findings[0].category == "template_residue"


def test_template_placeholder_rule_finds_unfilled_report_number() -> None:
    findings = TemplatePlaceholderRule().evaluate(
        [document(["中立国际评报字【2026】第XXXXX号"])]
    )

    assert len(findings) == 1


def test_score_conservation_rule_flags_non_100_total() -> None:
    findings = ScoreConservationRule().evaluate(
        [
            document(
                ["A1=总分 | B1=99"],
                extension=".xlsx",
                role=FileRole.CALCULATION_WORKBOOK,
            )
        ]
    )

    assert len(findings) == 1
    assert findings[0].category == "score_or_weight_not_conserved"


def test_conclusion_amount_consistency_rule_compares_report_and_workbook() -> None:
    findings = ConclusionAmountConsistencyRule().evaluate(
        [
            document(
                ["评估结论为100.00万元"],
                role=FileRole.MAIN_REPORT,
                file_id="REPORT",
            ),
            document(
                ["A1=评估值 | B1=101.00"],
                extension=".xlsx",
                role=FileRole.CALCULATION_WORKBOOK,
                file_id="WORKBOOK",
            ),
        ]
    )

    assert len(findings) == 1
    assert findings[0].source_file_id == "REPORT"
    assert findings[0].risk_level.value == "critical"
