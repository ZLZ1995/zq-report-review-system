from __future__ import annotations

import json
from pathlib import Path

import pytest

from asset_based_agent.report_review_app.domain.enums import (
    FileRole,
    ProjectStatus,
    RiskLevel,
    RoundStatus,
)
from asset_based_agent.report_review_app.domain.models import IssueLocation
from asset_based_agent.report_review_app.repositories.project_repository import (
    ProjectRepository,
)
from asset_based_agent.report_review_app.services.audit_orchestrator import (
    AuditOrchestrator,
    SourceFileChangedError,
)
from asset_based_agent.report_review_app.services.document_extraction_service import (
    DocumentChunk,
    ExtractedDocument,
)
from asset_based_agent.report_review_app.services.file_service import FileImportService
from asset_based_agent.report_review_app.services.privacy_filter import (
    PrivacyChunkSelector,
)
from asset_based_agent.report_review_app.services.review_llm_client import (
    OpenAICompatibleReviewLlm,
    ReviewNetworkError,
    ReviewResponseSchemaError,
)
from asset_based_agent.report_review_app.services.rule_registry import (
    IssueCandidate,
    RuleRegistry,
)


class FakeExtractor:
    def __init__(self, mutate_source: bool = False) -> None:
        self.mutate_source = mutate_source

    def extract(self, source_file):
        if self.mutate_source:
            Path(source_file.original_path).write_bytes(b"changed")
        return ExtractedDocument(
            source_file=source_file,
            extraction_mode="fake",
            chunks=[
                DocumentChunk(
                    chunk_id=f"{source_file.file_id}:1",
                    source_file_id=source_file.file_id,
                    source_file_name=source_file.original_name,
                    role=source_file.role,
                    text="待审核内容",
                    location=IssueLocation(paragraph=1),
                    reference_only=source_file.extension == ".pdf",
                )
            ],
        )


class FakeLlm:
    def review_batches(self, batches):
        findings = []
        for batch in batches:
            for chunk in batch.chunks:
                findings.append(
                    IssueCandidate(
                        source_file_id=chunk.source_file_id,
                        source_file_name=chunk.source_file_name,
                        category="llm_check",
                        risk_level=RiskLevel.HIGH,
                        location=chunk.location,
                        original_text=chunk.text,
                        description="模型发现的问题",
                        confidence=0.9,
                        rule_id="llm.review.v1",
                    )
                )
        return findings


class FakeSchemaErrorLlm:
    def review_batches(self, batches):
        raise ReviewResponseSchemaError(
            "LLM review response failed schema validation: "
            "issues.0.evidence_summaries.0: invalid value"
        )


class FakeProgressNetworkErrorLlm:
    def review_batches(self, batches, progress_callback=None):
        assert progress_callback is not None
        progress_callback(
            {
                "state": "retrying",
                "batch_index": 2,
                "batch_total": 5,
                "attempt": 3,
                "attempt_total": 3,
            }
        )
        raise ReviewNetworkError("LLM network request failed: IncompleteRead")


class HiddenSheetExtractor:
    def extract(self, source_file):
        return ExtractedDocument(
            source_file=source_file,
            extraction_mode="fake-workbook",
            chunks=[
                DocumentChunk(
                    chunk_id=f"{source_file.file_id}:visible",
                    source_file_id=source_file.file_id,
                    source_file_name=source_file.original_name,
                    role=source_file.role,
                    text="visible summary",
                    location=IssueLocation(table="评估结果汇总表", cell="A1"),
                ),
                DocumentChunk(
                    chunk_id=f"{source_file.file_id}:hidden",
                    source_file_id=source_file.file_id,
                    source_file_name=source_file.original_name,
                    role=source_file.role,
                    text="hidden supporting data",
                    location=IssueLocation(table="隐藏数据", cell="A1"),
                    reference_only=True,
                ),
            ],
        )


class FalseMissingRowLlm:
    def review_batches(self, batches):
        workbook_chunk = next(
            chunk
            for batch in batches
            for chunk in batch.chunks
            if chunk.location.cell == "row:20"
        )
        return [
            IssueCandidate(
                source_file_id=workbook_chunk.source_file_id,
                source_file_name=workbook_chunk.source_file_name,
                category="formula_error",
                risk_level=RiskLevel.HIGH,
                location=workbook_chunk.location,
                original_text=workbook_chunk.text,
                description="合计公式引用的第7、13、19行不存在。",
                confidence=0.9,
                rule_id="llm.review.v1",
            )
        ]


class UnsupportedTaxConclusionLlm:
    def review_batches(self, batches):
        chunk = batches[0].chunks[0]
        return [
            IssueCandidate(
                source_file_id=chunk.source_file_id,
                source_file_name=chunk.source_file_name,
                category="tax",
                risk_level=RiskLevel.HIGH,
                location=chunk.location,
                original_text=chunk.text,
                description="不含税价格使用13%税率错误，应按3%计算。",
                evidence_summaries=["购置时产权持有人为小规模纳税人。"],
                confidence=0.9,
                rule_id="llm.review.v1",
            )
        ]


class WorkbookRowsExtractor:
    def extract(self, source_file):
        return ExtractedDocument(
            source_file=source_file,
            extraction_mode="fake-workbook",
            chunks=[
                DocumentChunk(
                    chunk_id=f"{source_file.file_id}:row-{row}",
                    source_file_id=source_file.file_id,
                    source_file_name=source_file.original_name,
                    role=source_file.role,
                    text=f"A{row}=小计",
                    location=IssueLocation(table="固定资产汇总", cell=f"row:{row}"),
                )
                for row in (7, 13, 19, 20)
            ],
        )


def make_project(tmp_path: Path):
    repository = ProjectRepository(tmp_path / "projects")
    project = repository.create("审核项目")
    report = tmp_path / "报告.docx"
    report.write_bytes(b"report")
    reference = tmp_path / "参考.pdf"
    reference.write_bytes(b"pdf")
    FileImportService(repository).import_files(
        project,
        [report, reference],
        round_number=1,
        role_overrides={
            str(report.resolve()): FileRole.MAIN_REPORT,
            str(reference.resolve()): FileRole.REFERENCE_DOCUMENT,
        },
    )
    return repository, project


def test_first_round_writes_structured_issues_and_filters_pdf_findings(
    tmp_path: Path,
) -> None:
    repository, project = make_project(tmp_path)
    orchestrator = AuditOrchestrator(
        repository,
        FakeExtractor(),
        RuleRegistry(),
        FakeLlm(),
        PrivacyChunkSelector(max_batch_characters=500),
    )

    result = orchestrator.run_first_round(project)
    payload = json.loads(Path(result.issues_path).read_text(encoding="utf-8"))

    assert result.status == RoundStatus.COMPLETED
    assert result.issue_count == 1
    assert payload["issues"][0]["source_file_name"] == "报告.docx"
    assert repository.get(project.project_id).status == ProjectStatus.READY
    assert (
        json.loads(Path(result.progress_path).read_text(encoding="utf-8"))["percent"]
        == 100
    )


def test_source_hash_change_fails_closed_and_writes_error_snapshot(
    tmp_path: Path,
) -> None:
    repository, project = make_project(tmp_path)
    orchestrator = AuditOrchestrator(
        repository,
        FakeExtractor(mutate_source=True),
        RuleRegistry(),
        FakeLlm(),
    )

    with pytest.raises(SourceFileChangedError):
        orchestrator.run_first_round(project)

    saved = repository.get(project.project_id)
    round_record = saved.rounds[0]
    error = json.loads(Path(round_record.error_snapshot_path).read_text(encoding="utf-8"))
    assert round_record.status == RoundStatus.FAILED_SOURCE_CHANGED
    assert error["error_type"] == "SourceFileChangedError"


def test_llm_schema_error_is_recorded_as_failed_schema(tmp_path: Path) -> None:
    repository, project = make_project(tmp_path)
    orchestrator = AuditOrchestrator(
        repository,
        FakeExtractor(),
        RuleRegistry(),
        FakeSchemaErrorLlm(),
    )

    with pytest.raises(ReviewResponseSchemaError):
        orchestrator.run_first_round(project)

    saved = repository.get(project.project_id)
    round_record = saved.rounds[0]
    error = json.loads(Path(round_record.error_snapshot_path).read_text(encoding="utf-8"))
    progress = json.loads(Path(round_record.progress_path).read_text(encoding="utf-8"))
    assert round_record.status == RoundStatus.FAILED_SCHEMA
    assert error["error_type"] == "ReviewResponseSchemaError"
    assert progress["percent"] >= 50


def test_network_pause_preserves_batch_and_retry_progress(tmp_path: Path) -> None:
    repository, project = make_project(tmp_path)
    orchestrator = AuditOrchestrator(
        repository,
        FakeExtractor(),
        RuleRegistry(),
        FakeProgressNetworkErrorLlm(),
    )

    with pytest.raises(ReviewNetworkError):
        orchestrator.run_first_round(project)

    round_record = repository.get(project.project_id).rounds[0]
    progress = json.loads(Path(round_record.progress_path).read_text(encoding="utf-8"))
    assert round_record.status == RoundStatus.PAUSED_NETWORK_ERROR
    assert progress["stage"] == "paused_network_error"
    assert progress["batch_index"] == 2
    assert progress["batch_total"] == 5
    assert progress["attempt"] == 3
    assert progress["attempt_total"] == 3
    assert "网络" in progress["detail"]


def test_deepseek_object_evidence_completes_round_without_changing_sources(
    tmp_path: Path,
    monkeypatch,
) -> None:
    repository, project = make_project(tmp_path)
    report = next(item for item in project.files if item.extension == ".docx")
    source_hashes = {
        item.file_id: Path(item.original_path).read_bytes() for item in project.files
    }
    llm = OpenAICompatibleReviewLlm(
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
                "source_file_id": report.file_id,
                "source_file_name": report.original_name,
                "category": "data_inconsistency",
                "risk_level": "high",
                "location": {"paragraph": 1},
                "original_text": "待审核内容",
                "description": "模型发现的问题",
                "evidence_summaries": [
                    {"content": "报告证据", "paragraph": 227}
                ],
                "confidence": 0.9,
                "rule_id": "llm.review.v1",
            }
        ]
    }
    monkeypatch.setattr(
        llm,
        "_post_json",
        lambda _url, _payload: {
            "choices": [{"message": {"content": json.dumps(response)}}]
        },
    )
    orchestrator = AuditOrchestrator(
        repository,
        FakeExtractor(),
        RuleRegistry(),
        llm,
        PrivacyChunkSelector(max_batch_characters=500),
    )

    result = orchestrator.run_first_round(project)
    payload = json.loads(Path(result.issues_path).read_text(encoding="utf-8"))

    assert result.status == RoundStatus.COMPLETED
    assert result.issue_count == 1
    assert payload["issues"][0]["evidence"][0]["summary"] == "第227段：报告证据"
    assert all(
        Path(item.original_path).read_bytes() == source_hashes[item.file_id]
        for item in project.files
    )


def test_hidden_dependency_sheet_cannot_become_issue_source(tmp_path: Path) -> None:
    repository = ProjectRepository(tmp_path / "projects")
    project = repository.create("审核项目")
    workbook = tmp_path / "评估明细表.xlsx"
    workbook.write_bytes(b"workbook")
    FileImportService(repository).import_files(
        project,
        [workbook],
        round_number=1,
        role_overrides={
            str(workbook.resolve()): FileRole.CALCULATION_WORKBOOK,
        },
    )
    orchestrator = AuditOrchestrator(
        repository,
        HiddenSheetExtractor(),
        RuleRegistry(),
        FakeLlm(),
        PrivacyChunkSelector(max_batch_characters=500),
    )

    result = orchestrator.run_first_round(project)
    payload = json.loads(Path(result.issues_path).read_text(encoding="utf-8"))

    assert result.issue_count == 1
    assert payload["issues"][0]["location"]["table"] == "评估结果汇总表"


def test_llm_missing_row_claim_is_rejected_when_rows_exist(tmp_path: Path) -> None:
    repository = ProjectRepository(tmp_path / "projects")
    project = repository.create("审核项目")
    workbook = tmp_path / "评估明细表.xlsx"
    workbook.write_bytes(b"workbook")
    FileImportService(repository).import_files(
        project,
        [workbook],
        round_number=1,
        role_overrides={
            str(workbook.resolve()): FileRole.CALCULATION_WORKBOOK,
        },
    )
    orchestrator = AuditOrchestrator(
        repository,
        WorkbookRowsExtractor(),
        RuleRegistry(),
        FalseMissingRowLlm(),
        PrivacyChunkSelector(max_batch_characters=500),
    )

    result = orchestrator.run_first_round(project)

    assert result.issue_count == 0


def test_unsupported_tax_conclusion_is_marked_uncertain(tmp_path: Path) -> None:
    repository, project = make_project(tmp_path)
    orchestrator = AuditOrchestrator(
        repository,
        FakeExtractor(),
        RuleRegistry(),
        UnsupportedTaxConclusionLlm(),
        PrivacyChunkSelector(max_batch_characters=500),
    )

    result = orchestrator.run_first_round(project)
    payload = json.loads(Path(result.issues_path).read_text(encoding="utf-8"))

    assert payload["issues"][0]["status"] == "uncertain"


def test_second_round_keeps_stable_issue_id_and_marks_unmodified(
    tmp_path: Path,
) -> None:
    repository, project = make_project(tmp_path)
    orchestrator = AuditOrchestrator(
        repository,
        FakeExtractor(),
        RuleRegistry(),
        FakeLlm(),
        PrivacyChunkSelector(max_batch_characters=500),
    )
    first_round = orchestrator.run_first_round(project)
    first_payload = json.loads(
        Path(first_round.issues_path).read_text(encoding="utf-8")
    )
    first_issue_id = first_payload["issues"][0]["issue_id"]
    old_report = next(item for item in project.files if item.extension == ".docx")
    replacement_path = tmp_path / "修改后报告.docx"
    replacement_path.write_bytes(b"updated report")
    FileImportService(repository).import_files(
        project,
        [replacement_path],
        round_number=2,
        role_overrides={
            str(replacement_path.resolve()): FileRole.MAIN_REPORT,
        },
        replacement_overrides={
            str(replacement_path.resolve()): old_report.file_id,
        },
    )

    second_round = orchestrator.run_round(project, 2)
    second_payload = json.loads(
        Path(second_round.issues_path).read_text(encoding="utf-8")
    )

    assert second_payload["issues"][0]["issue_id"] == first_issue_id
    assert second_payload["issues"][0]["status"] == "unmodified"
