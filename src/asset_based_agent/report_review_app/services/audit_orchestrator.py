"""Single-task, resumable first-round read-only audit orchestration."""

from __future__ import annotations

import hashlib
import json
import threading
import uuid
from pathlib import Path

from ..atomic_json import write_json_atomic
from ..domain.enums import IssueStatus, ProjectStatus, RoundStatus
from ..domain.models import (
    AuditProject,
    AuditRound,
    IssueEvidence,
    IssueHistoryEntry,
    ReviewIssue,
    SourceFile,
    utc_now,
)
from ..repositories.issue_repository import IssueRepository
from ..repositories.project_repository import ProjectRepository
from .audit_artifact_service import AuditArtifactService
from .candidate_validation_service import CandidateValidationService
from .document_extraction_service import DocumentExtractionService, ExtractedDocument
from .file_service import sha256_file
from .issue_aggregation_service import IssueAggregationService
from .issue_matcher import IssueMatcher
from .privacy_filter import PrivacyChunkSelector
from .report_review_agent import ReportReviewAgent
from .review_llm_client import (
    ReviewLlm,
    ReviewNetworkError,
    ReviewResponseSchemaError,
)
from .rule_registry import IssueCandidate, RuleRegistry
from .tax_evidence_policy import TaxEvidencePolicy


class AuditAlreadyRunningError(RuntimeError):
    pass


class SourceFileChangedError(RuntimeError):
    pass


class AuditOrchestrator:
    def __init__(
        self,
        repository: ProjectRepository,
        extractor: DocumentExtractionService,
        rules: RuleRegistry,
        llm: ReviewLlm,
        selector: PrivacyChunkSelector | None = None,
        issue_repository: IssueRepository | None = None,
        issue_matcher: IssueMatcher | None = None,
    ) -> None:
        self.repository = repository
        self.extractor = extractor
        self.rules = rules
        self.llm = llm
        self.selector = selector or PrivacyChunkSelector()
        self.issue_repository = issue_repository or IssueRepository()
        self.issue_matcher = issue_matcher or IssueMatcher()
        self.candidate_validator = CandidateValidationService()
        self.tax_evidence_policy = TaxEvidencePolicy()
        self.issue_aggregator = IssueAggregationService()
        self.review_agent = ReportReviewAgent(self.llm, self.selector)
        self.artifact_service = AuditArtifactService()
        self._active_lock = threading.Lock()

    def run_first_round(self, project: AuditProject) -> AuditRound:
        return self.run_round(project, 1)

    def run_round(self, project: AuditProject, round_number: int) -> AuditRound:
        if not self._active_lock.acquire(blocking=False):
            raise AuditAlreadyRunningError("another audit task is already running")
        try:
            return self._run_round(project, round_number)
        finally:
            self._active_lock.release()

    def _run_round(self, project: AuditProject, round_number: int) -> AuditRound:
        if round_number < 1:
            raise ValueError("round_number must be at least 1")
        files = [item for item in project.files if item.round_number == round_number]
        if not files:
            raise ValueError(f"round {round_number} has no source files")
        previous_issues = self._previous_issues(project, round_number)
        round_record = self._prepare_round(project, files, round_number)
        baseline_hashes = {item.file_id: sha256_file(Path(item.original_path)) for item in files}
        try:
            self._progress(
                project,
                round_record,
                RoundStatus.EXTRACTING,
                10,
                detail="正在读取并解析本地文件",
            )
            documents = [self.extractor.extract(item) for item in files]
            round_dir = Path(round_record.issues_path).parent
            self.artifact_service.write_extraction(round_dir, documents)
            self._progress(
                project,
                round_record,
                RoundStatus.RUNNING_LOCAL_RULES,
                35,
                detail="正在执行本地确定性审核规则",
            )
            local_candidates = self.rules.evaluate(documents)
            self._progress(
                project,
                round_record,
                RoundStatus.SELECTING_LLM_CHUNKS,
                50,
                detail="正在整理允许发送给模型的审核片段",
            )
            self._progress(
                project,
                round_record,
                RoundStatus.RUNNING_LLM_REVIEW,
                55,
                detail="正在准备调用大模型",
            )
            set_round_number = getattr(self.llm, "set_round_number", None)
            if callable(set_round_number):
                set_round_number(round_number)
            set_client_job_id = getattr(self.llm, "set_client_job_id", None)
            if callable(set_client_job_id):
                set_client_job_id(f"PROJECT-{project.project_id}-ROUND-{round_number}")
            llm_candidates = self.review_agent.review(
                documents,
                progress_callback=lambda payload: self._record_llm_progress(
                    project,
                    round_record,
                    payload,
                ),
            )
            self.artifact_service.write_candidates(
                round_dir,
                local_candidates,
                llm_candidates,
            )
            candidates = [*local_candidates, *llm_candidates]
            candidates = self.issue_aggregator.aggregate(candidates)
            self._progress(
                project,
                round_record,
                RoundStatus.NORMALIZING_ISSUES,
                84,
                detail="正在验证、去重并整理审核意见",
            )
            issues = self._normalize_candidates(
                candidates,
                files,
                documents,
                candidate_validator=self.candidate_validator,
                tax_evidence_policy=self.tax_evidence_policy,
                round_number=round_number,
            )
            if previous_issues:
                self._progress(
                    project,
                    round_record,
                    RoundStatus.MATCHING_PREVIOUS_ISSUES,
                    89,
                    detail="正在核对上一轮问题的修改情况",
                )
                replacements = {
                    item.replaces_file_id: item.file_id
                    for item in files
                    if item.replaces_file_id
                }
                issues = self.issue_matcher.reconcile(
                    previous_issues,
                    issues,
                    round_number=round_number,
                    source_replacements=replacements,
                )
            self._progress(
                project,
                round_record,
                RoundStatus.VERIFYING_SOURCE_HASHES,
                95,
                detail="正在确认源文件未被修改",
            )
            self._verify_hashes(files, baseline_hashes)
            self.issue_repository.save_issues(
                Path(round_record.issues_path),
                project_id=project.project_id,
                round_number=round_number,
                issues=issues,
            )
            round_record.issue_count = len(issues)
            round_record.status = RoundStatus.COMPLETED
            round_record.updated_at = utc_now()
            project.status = ProjectStatus.READY
            self.repository.save(project)
            self._write_progress(
                Path(round_record.progress_path),
                RoundStatus.COMPLETED,
                100,
                detail="审核已完成",
            )
            return round_record
        except SourceFileChangedError as exc:
            self._fail(project, round_record, RoundStatus.FAILED_SOURCE_CHANGED, exc)
            raise
        except ReviewNetworkError as exc:
            self._fail(project, round_record, RoundStatus.PAUSED_NETWORK_ERROR, exc)
            project.status = ProjectStatus.PAUSED
            self.repository.save(project)
            raise
        except ReviewResponseSchemaError as exc:
            self._fail(project, round_record, RoundStatus.FAILED_SCHEMA, exc)
            raise
        except Exception as exc:
            self._fail(project, round_record, RoundStatus.FAILED_INTERNAL, exc)
            raise

    def _prepare_round(
        self,
        project: AuditProject,
        files: list[SourceFile],
        round_number: int,
    ) -> AuditRound:
        round_dir = (
            Path(project.project_path)
            / "rounds"
            / f"round-{round_number:03d}"
        )
        round_dir.mkdir(parents=True, exist_ok=True)
        record = AuditRound(
            round_id=f"ROUND-{uuid.uuid4().hex.upper()}",
            round_number=round_number,
            status=RoundStatus.PREPARING,
            source_file_ids=[item.file_id for item in files],
            progress_path=str(round_dir / "progress.json"),
            issues_path=str(round_dir / "issues.json"),
            error_snapshot_path=str(round_dir / "error_snapshot.json"),
        )
        project.rounds = [
            item for item in project.rounds if item.round_number != round_number
        ]
        project.rounds.append(record)
        project.status = ProjectStatus.AUDITING
        self.repository.save(project)
        self._write_progress(
            Path(record.progress_path),
            RoundStatus.PREPARING,
            0,
            detail="正在准备审核任务",
        )
        return record

    def _progress(
        self,
        project: AuditProject,
        record: AuditRound,
        status: RoundStatus,
        percent: int,
        *,
        detail: str = "",
        **progress_fields: object,
    ) -> None:
        record.status = status
        record.updated_at = utc_now()
        self.repository.save(project)
        self._write_progress(
            Path(record.progress_path),
            status,
            percent,
            detail=detail,
            **progress_fields,
        )

    def _record_llm_progress(
        self,
        project: AuditProject,
        record: AuditRound,
        payload: dict[str, object],
    ) -> None:
        batch_index = max(1, int(payload.get("batch_index") or 1))
        batch_total = max(batch_index, int(payload.get("batch_total") or 1))
        attempt = max(1, int(payload.get("attempt") or 1))
        attempt_total = max(attempt, int(payload.get("attempt_total") or 1))
        state = str(payload.get("state") or "requesting")
        completed_batches = batch_index if state == "completed" else batch_index - 1
        percent = 55 + round(25 * completed_batches / batch_total)
        detail = {
            "requesting": "正在调用大模型审核当前批次",
            "retrying": "模型响应中断，正在自动重试",
            "completed": "当前模型审核批次已完成",
        }.get(state, "正在调用大模型")
        self._progress(
            project,
            record,
            RoundStatus.RUNNING_LLM_REVIEW,
            min(80, percent),
            detail=detail,
            batch_index=batch_index,
            batch_total=batch_total,
            attempt=attempt,
            attempt_total=attempt_total,
            llm_state=state,
        )

    def _fail(
        self,
        project: AuditProject,
        record: AuditRound,
        status: RoundStatus,
        exc: Exception,
    ) -> None:
        progress_path = Path(record.progress_path)
        previous_progress = _read_progress_payload(progress_path)
        percent = max(0, min(100, int(previous_progress.get("percent") or 0)))
        record.status = status
        record.updated_at = utc_now()
        project.status = ProjectStatus.FAILED
        self.repository.save(project)
        _write_json_atomic(
            Path(record.error_snapshot_path),
            {
                "status": status.value,
                "error_type": type(exc).__name__,
                "message": str(exc),
                "time": utc_now().isoformat(),
            },
        )
        previous_progress.update(
            {
                "stage": status.value,
                "percent": percent,
                "detail": (
                    "网络连接中断，审核已暂停"
                    if status == RoundStatus.PAUSED_NETWORK_ERROR
                    else "审核未完成"
                ),
                "updated_at": utc_now().isoformat(),
            }
        )
        _write_json_atomic(progress_path, previous_progress)

    @staticmethod
    def _verify_hashes(
        files: list[SourceFile],
        baseline_hashes: dict[str, str],
    ) -> None:
        for source in files:
            if sha256_file(Path(source.original_path)) != baseline_hashes[source.file_id]:
                raise SourceFileChangedError(
                    f"source file changed during review: {source.original_name}"
                )

    @staticmethod
    def _normalize_candidates(
        candidates: list[IssueCandidate],
        files: list[SourceFile],
        documents: list[ExtractedDocument],
        *,
        candidate_validator: CandidateValidationService | None = None,
        tax_evidence_policy: TaxEvidencePolicy | None = None,
        round_number: int,
    ) -> list[ReviewIssue]:
        allowed = {
            item.file_id: item
            for item in files
            if item.extension.lower() in {".docx", ".xlsx", ".xlsm"}
        }
        reference_ids = {
            document.source_file.file_id
            for document in documents
            if document.source_file.extension.lower() == ".pdf"
        }
        reference_locations = {
            (chunk.source_file_id, chunk.location.table)
            for document in documents
            for chunk in document.chunks
            if chunk.reference_only and chunk.location.table
        }
        results: dict[str, ReviewIssue] = {}
        validator = candidate_validator or CandidateValidationService()
        tax_policy = tax_evidence_policy or TaxEvidencePolicy()
        for candidate in candidates:
            if not validator.accepts(candidate, documents):
                continue
            candidate_status = (
                IssueStatus.UNCERTAIN
                if tax_policy.requires_verification(candidate)
                else IssueStatus.NEW
            )
            if candidate.source_file_id in reference_ids:
                continue
            if (
                candidate.source_file_id,
                candidate.location.table,
            ) in reference_locations and not candidate.allow_reference_source:
                continue
            source = allowed.get(candidate.source_file_id)
            if source is None:
                continue
            fingerprint = _candidate_fingerprint(candidate)
            if fingerprint in results:
                continue
            results[fingerprint] = ReviewIssue(
                issue_id=f"ISSUE-{uuid.uuid4().hex.upper()}",
                fingerprint=fingerprint,
                source_file_id=source.file_id,
                source_file_name=source.original_name,
                category=candidate.category,
                risk_level=candidate.risk_level,
                status=candidate_status,
                location=candidate.location,
                original_text=candidate.original_text,
                description=candidate.description,
                evidence=[
                    IssueEvidence(
                        evidence_type="review_basis",
                        source_file_id=source.file_id,
                        summary=summary,
                    )
                    for summary in candidate.evidence_summaries
                ],
                recommendation=candidate.recommendation,
                confidence=candidate.confidence,
                first_seen_round=round_number,
                last_seen_round=round_number,
                history=[
                    IssueHistoryEntry(
                        round_number=round_number,
                        status=candidate_status,
                        note=candidate.rule_id,
                    )
                ],
                origin=(
                    "llm"
                    if candidate.rule_id == "llm.review.v1"
                    else "deterministic_rule"
                ),
                rule_id=candidate.rule_id,
                evidence_state=(
                    "insufficient"
                    if candidate_status == IssueStatus.UNCERTAIN
                    else "sufficient"
                ),
                occurrences=candidate.occurrences or [candidate.location],
            )
        return list(results.values())

    def _previous_issues(
        self,
        project: AuditProject,
        round_number: int,
    ) -> list[ReviewIssue]:
        if round_number <= 1:
            return []
        previous = next(
            (
                item
                for item in project.rounds
                if item.round_number == round_number - 1
            ),
            None,
        )
        if previous is None:
            raise ValueError(f"round {round_number - 1} is missing")
        return self.issue_repository.load_issues(Path(previous.issues_path))

    @staticmethod
    def _write_progress(
        path: Path,
        status: RoundStatus,
        percent: int,
        *,
        detail: str = "",
        **progress_fields: object,
    ) -> None:
        payload: dict[str, object] = {
            "stage": status.value,
            "percent": percent,
            "detail": detail,
            "updated_at": utc_now().isoformat(),
        }
        payload.update(progress_fields)
        _write_json_atomic(path, payload)


def _candidate_fingerprint(candidate: IssueCandidate) -> str:
    location = json.dumps(
        candidate.location.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
    )
    raw = "|".join(
        [
            candidate.source_file_id,
            candidate.category,
            location,
            candidate.original_text.strip(),
            candidate.description.strip(),
        ]
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _write_json_atomic(path: Path, payload: dict[str, object]) -> None:
    write_json_atomic(path, payload)


def _read_progress_percent(path: Path) -> int:
    payload = _read_progress_payload(path)
    try:
        return max(0, min(100, int(payload.get("percent", 0))))
    except (ValueError, TypeError):
        return 0


def _read_progress_payload(path: Path) -> dict[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}
