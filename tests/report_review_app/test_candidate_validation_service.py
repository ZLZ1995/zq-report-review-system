from asset_based_agent.report_review_app.domain.enums import FileRole, RiskLevel
from asset_based_agent.report_review_app.domain.models import IssueLocation, SourceFile
from asset_based_agent.report_review_app.services.candidate_validation_service import (
    CandidateValidationService,
)
from asset_based_agent.report_review_app.services.document_extraction_service import (
    DocumentChunk,
    ExtractedDocument,
)
from asset_based_agent.report_review_app.services.rule_registry import IssueCandidate


def workbook_document(
    *,
    sheet: str,
    row: int,
    text: str,
    cached_values: dict[str, object],
) -> ExtractedDocument:
    source = SourceFile(
        file_id="FILE-1",
        original_name="workbook.xlsx",
        extension=".xlsx",
        sha256="0" * 64,
        size_bytes=1,
        role=FileRole.CALCULATION_WORKBOOK,
        round_number=1,
        original_path="workbook.xlsx",
    )
    return ExtractedDocument(
        source_file=source,
        extraction_mode="test",
        chunks=[
            DocumentChunk(
                chunk_id=f"FILE-1:{sheet}:{row}",
                source_file_id="FILE-1",
                source_file_name="workbook.xlsx",
                role=FileRole.CALCULATION_WORKBOOK,
                text=text,
                location=IssueLocation(table=sheet, cell=f"row:{row}"),
                cached_values=cached_values,
            )
        ],
    )


def candidate(sheet: str, row: int, description: str, original: str) -> IssueCandidate:
    return IssueCandidate(
        source_file_id="FILE-1",
        source_file_name="workbook.xlsx",
        category="data_inconsistency",
        risk_level=RiskLevel.HIGH,
        location=IssueLocation(table=sheet, cell=f"row:{row}"),
        original_text=original,
        description=description,
        confidence=0.9,
        rule_id="llm.review.v1",
    )


def test_zero_template_row_cannot_prove_asset_exists() -> None:
    document = workbook_document(
        sheet="非流动资产汇总",
        row=9,
        text="A9=4-4 | B9=长期股权投资 | C9=0 | D9=0 | E9=0",
        cached_values={"C9": 0, "D9": 0, "E9": 0, "F9": 0},
    )
    finding = candidate(
        "非流动资产汇总",
        9,
        "存在长期股权投资减值准备，表明应存在长期股权投资，数据不一致。",
        document.chunks[0].text,
    )

    assert not CandidateValidationService().accepts(finding, [document])


def test_missing_columns_on_zero_balance_row_are_suppressed() -> None:
    document = workbook_document(
        sheet="固定资产汇总",
        row=11,
        text="A11=4-6-4 | B11=固定资产-井巷 | C11=0 | D11=0",
        cached_values={"C11": 0, "D11": 0, "E11": 0, "F11": 0},
    )
    finding = candidate(
        "固定资产汇总",
        11,
        "井巷行缺少评估价值及增值额列公式，可能导致汇总数据缺失。",
        document.chunks[0].text,
    )

    assert not CandidateValidationService().accepts(finding, [document])


def test_missing_columns_on_nonzero_row_are_not_suppressed() -> None:
    document = workbook_document(
        sheet="固定资产汇总",
        row=11,
        text="A11=4-6-4 | B11=固定资产-井巷 | C11=100",
        cached_values={"C11": 100, "D11": 90},
    )
    finding = candidate(
        "固定资产汇总",
        11,
        "井巷行缺少评估价值及增值额列公式，可能导致汇总数据缺失。",
        document.chunks[0].text,
    )

    assert CandidateValidationService().accepts(finding, [document])
