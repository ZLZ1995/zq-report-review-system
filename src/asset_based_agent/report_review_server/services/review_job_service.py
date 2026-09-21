"""Encrypted server-side review jobs with round-level billing reservation."""

from __future__ import annotations

import hashlib
import json
from datetime import timedelta

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..config import ServerSettings
from ..crypto import SecretCipher
from ..models import ModelDefinition, ReviewJob, ReviewJobEvent, utc_now
from ..schemas import ReviewJobCreateRequest, ReviewJobResponse
from .auth_service import ServiceError, is_expired
from .metered_model_service import BillingReconciliationRequired, MeteredModelService
from .provider_gateway import NormalizedUsage, ProviderClient
from .server_review_agent import ServerReviewAgent, ServerReviewBatch


class ReviewJobService:
    def __init__(self, settings: ServerSettings, provider_client: ProviderClient) -> None:
        self.cipher = SecretCipher(settings.encryption_key_bytes())
        self.metered = MeteredModelService(settings, provider_client)
        self.agent = ServerReviewAgent()

    def create_job(
        self,
        db: Session,
        *,
        user_id: str,
        payload: ReviewJobCreateRequest,
    ) -> ReviewJob:
        context_json = _canonical_context(payload)
        context_hash = hashlib.sha256(context_json.encode("utf-8")).hexdigest()
        existing = db.scalar(
            select(ReviewJob).where(
                ReviewJob.user_id == user_id,
                ReviewJob.client_job_id == payload.client_job_id,
            )
        )
        if existing is not None:
            if existing.context_hash != context_hash:
                raise ServiceError(
                    "idempotency_conflict",
                    "相同任务编号对应了不同审核内容。",
                    409,
                )
            return existing

        batches = self.agent.build_batches(payload.chunks, payload.skill_instructions, payload.user_request)
        model = db.get(ModelDefinition, payload.model_id)
        if model is None or not model.enabled:
            raise ServiceError("model_unavailable", "模型当前不可用。", 409)
        estimated_usages = [
            self._estimated_usage(batch, model)
            for batch in batches
        ]
        try:
            hold = self.metered.reserve(
                db,
                user_id=user_id,
                model_id=payload.model_id,
                client_request_id=f"review:{payload.client_job_id}",
                estimated_usages=estimated_usages,
                commit=False,
                hold_minutes=24 * 60,
            )
            job = ReviewJob(
                user_id=user_id,
                model_id=payload.model_id,
                hold_id=hold.hold_id,
                client_job_id=payload.client_job_id,
                round_number=payload.round_number,
                context_hash=context_hash,
                batch_count=len(batches),
                context_expires_at=utc_now() + timedelta(hours=24),
            )
            db.add(job)
            db.flush()
            self._record_event(db, job, "queued")
            job.context_ciphertext = self.cipher.encrypt(
                context_json,
                purpose=f"review-context:{job.job_id}",
            )
            db.commit()
        except IntegrityError:
            db.rollback()
            raced = db.scalar(
                select(ReviewJob).where(
                    ReviewJob.user_id == user_id,
                    ReviewJob.client_job_id == payload.client_job_id,
                )
            )
            if raced is None or raced.context_hash != context_hash:
                raise
            return raced
        db.refresh(job)
        return job

    def execute_job(
        self,
        db: Session,
        *,
        user_id: str,
        job_id: str,
        worker_id: str = "inline",
    ) -> ReviewJobResponse:
        job = self._get_owned_job(db, user_id=user_id, job_id=job_id)
        if job.status == "queued" and job.execution_requested_at is None:
            self.request_execution(db, user_id=user_id, job_id=job_id)
            db.refresh(job)
        if job.status == "succeeded":
            return self.to_response(job)
        if job.status == "failed":
            if job.error_code == "billing_reconciliation_required":
                raise BillingReconciliationRequired()
            raise ServiceError(
                "review_job_failed",
                "审核任务已失败，请创建新任务后重试。",
                409,
            )
        if job.status != "queued":
            raise ServiceError("review_job_in_progress", "审核任务正在执行。", 409)
        if not job.context_ciphertext or not job.context_expires_at:
            raise ServiceError("review_context_expired", "审核临时上下文已过期。", 410)
        if is_expired(job.context_expires_at):
            raise ServiceError("review_context_expired", "审核临时上下文已过期。", 410)

        payload = ReviewJobCreateRequest.model_validate_json(
            self.cipher.decrypt(
                job.context_ciphertext,
                purpose=f"review-context:{job.job_id}",
            )
        )
        batches = self.agent.build_batches(payload.chunks, payload.skill_instructions, payload.user_request)
        model = db.get(ModelDefinition, job.model_id)
        if model is None:
            raise ServiceError("model_unavailable", "模型当前不可用。", 409)
        claimed_job_id = db.scalar(
            update(ReviewJob)
            .where(
                ReviewJob.job_id == job_id,
                ReviewJob.user_id == user_id,
                ReviewJob.status == "queued",
                ReviewJob.execution_requested_at.is_not(None),
            )
            .values(
                status="running",
                started_at=utc_now(),
                error_code=None,
                worker_id=worker_id,
                lease_expires_at=utc_now() + timedelta(minutes=15),
            )
            .returning(ReviewJob.job_id)
        )
        db.commit()
        if claimed_job_id is None:
            raise ServiceError("review_job_in_progress", "审核任务正在执行。", 409)
        db.refresh(job)
        self._record_event(db, job, "running")
        db.commit()

        issues: list[dict[str, object]] = []
        try:
            for index, batch in enumerate(batches, start=1):
                db.refresh(job)
                if job.error_code == 'cancel_requested':
                    return self._finish_cancel(db, job)
                job.lease_expires_at = utc_now() + timedelta(minutes=15)
                db.commit()
                request_payload = self.agent.request_payload(batch)
                metered_result = self.metered.execute(
                    db,
                    user_id=user_id,
                    model_id=job.model_id,
                    client_request_id=f"{job.client_job_id}:batch:{index}",
                    estimated_usage=self._estimated_usage(batch, model),
                    payload=request_payload,
                    external_hold_id=job.hold_id,
                    defer_settlement=True,
                )
                db.refresh(job)
                if job.error_code == 'cancel_requested':
                    return self._finish_cancel(db, job)
                issues.extend(
                    self.agent.parse_issues(metered_result.payload, batch=batch)
                )
                job.completed_batches = index
                job.progress_percent = int(index * 100 / len(batches))
                # Publish validated batch output under the same encrypted TTL
                # policy as the final result, for incremental client delivery.
                job.result_ciphertext = self.cipher.encrypt(
                    json.dumps({"issues": issues}, ensure_ascii=False),
                    purpose=f"review-result:{job.job_id}",
                )
                job.result_expires_at = utc_now() + timedelta(hours=24)
                self._record_event(db, job, "progress")
                db.commit()
        except Exception as exc:
            job.status = "failed"
            job.error_code = getattr(exc, "code", "review_execution_failed")
            job.completed_at = utc_now()
            job.worker_id = None
            job.lease_expires_at = None
            self._record_event(db, job, "failed")
            db.commit()
            if isinstance(exc, BillingReconciliationRequired):
                raise
            self.metered.capture_hold(
                db,
                hold_id=job.hold_id,
                reference_id=job.job_id,
            )
            raise

        result_json = json.dumps(
            {"issues": issues}, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        job.result_ciphertext = self.cipher.encrypt(
            result_json,
            purpose=f"review-result:{job.job_id}",
        )
        job.result_expires_at = utc_now() + timedelta(hours=24)
        job.status = "succeeded"
        job.progress_percent = 100
        job.completed_at = utc_now()
        job.worker_id = None
        job.lease_expires_at = None
        self._record_event(db, job, "succeeded")
        db.commit()
        self.metered.capture_hold(
            db,
            hold_id=job.hold_id,
            reference_id=job.job_id,
        )
        db.refresh(job)
        return self.to_response(job)

    def get_job(self, db: Session, *, user_id: str, job_id: str) -> ReviewJobResponse:
        return self.to_response(self._get_owned_job(db, user_id=user_id, job_id=job_id))

    def request_execution(self, db: Session, *, user_id: str, job_id: str) -> ReviewJobResponse:
        job = self._get_owned_job(db, user_id=user_id, job_id=job_id)
        if job.status in {"succeeded", "running"}:
            return self.to_response(job)
        if job.status != "queued":
            raise ServiceError("review_job_not_executable", "审核任务不能再次执行。", 409)
        if job.execution_requested_at is None:
            job.execution_requested_at = utc_now()
            self._record_event(db, job, "execution_requested")
            db.commit()
            db.refresh(job)
        return self.to_response(job)

    def fail_requested_job(
        self,
        db: Session,
        *,
        user_id: str,
        job_id: str,
        error_code: str = "review_execution_rejected",
    ) -> ReviewJobResponse:
        """Close a requested job that failed before any provider call began."""
        job = self._get_owned_job(db, user_id=user_id, job_id=job_id)
        if job.status != "queued" or job.execution_requested_at is None:
            return self.to_response(job)
        job.status = "failed"
        job.error_code = error_code
        job.completed_at = utc_now()
        job.worker_id = None
        job.lease_expires_at = None
        self._record_event(db, job, "failed")
        db.commit()
        self.metered.capture_hold(
            db,
            hold_id=job.hold_id,
            reference_id=job.job_id,
        )
        db.refresh(job)
        return self.to_response(job)

    def recover_interrupted(self, db: Session) -> list[tuple[str, str]]:
        interrupted = list(db.scalars(select(ReviewJob).where(ReviewJob.status == "running")))
        for job in interrupted:
            job.status = "queued"
            job.started_at = None
            job.error_code = "recovered_after_restart"
            job.worker_id = None
            job.lease_expires_at = None
            self._record_event(db, job, "recovered")
        db.commit()
        rows = db.execute(select(ReviewJob.user_id, ReviewJob.job_id).where(
            ReviewJob.status == "queued",
            ReviewJob.execution_requested_at.is_not(None),
        ))
        return [(user_id, job_id) for user_id, job_id in rows]

    def list_events(self, db: Session, *, user_id: str, job_id: str,
                    after_sequence: int = 0) -> list[ReviewJobEvent]:
        self._get_owned_job(db, user_id=user_id, job_id=job_id)
        return list(db.scalars(select(ReviewJobEvent).where(
            ReviewJobEvent.job_id == job_id,
            ReviewJobEvent.sequence > after_sequence,
        ).order_by(ReviewJobEvent.sequence)))

    def _finish_cancel(self, db, job):
        job.status = 'cancelled'
        job.completed_at = utc_now()
        job.worker_id = None
        job.lease_expires_at = None
        self._record_event(db, job, 'cancelled')
        db.commit()
        self.metered.capture_hold(db, hold_id=job.hold_id, reference_id=job.job_id)
        db.refresh(job)
        return self.to_response(job)

    def cancel_job(self, db: Session, *, user_id: str, job_id: str) -> ReviewJobResponse:
        job = self._get_owned_job(db, user_id=user_id, job_id=job_id)
        cancelled = db.scalar(update(ReviewJob).where(
            ReviewJob.job_id == job_id, ReviewJob.user_id == user_id, ReviewJob.status == 'queued'
        ).values(status='cancelled', error_code='cancel_requested', completed_at=utc_now())
            .returning(ReviewJob.job_id))
        if cancelled is None:
            db.execute(update(ReviewJob).where(
                ReviewJob.job_id == job_id, ReviewJob.user_id == user_id, ReviewJob.status == 'running'
            ).values(error_code='cancel_requested'))
        db.commit()
        db.refresh(job)
        self._record_event(db, job, 'cancelled' if cancelled is not None else 'cancel_requested')
        db.commit()
        if cancelled is not None:
            self.metered.capture_hold(db, hold_id=job.hold_id, reference_id=job.job_id)
        db.refresh(job)
        return self.to_response(job)

    def to_response(self, job: ReviewJob) -> ReviewJobResponse:
        issues: list[dict[str, object]] = []
        if (
            job.result_ciphertext
            and job.result_expires_at
            and not is_expired(job.result_expires_at)
        ):
            result = json.loads(
                self.cipher.decrypt(
                    job.result_ciphertext,
                    purpose=f"review-result:{job.job_id}",
                )
            )
            raw_issues = result.get("issues", [])
            if isinstance(raw_issues, list):
                issues = [item for item in raw_issues if isinstance(item, dict)]
        return ReviewJobResponse(
            job_id=job.job_id,
            client_job_id=job.client_job_id,
            model_id=job.model_id,
            round_number=job.round_number,
            status=job.status,
            batch_count=job.batch_count,
            completed_batches=job.completed_batches,
            progress_percent=job.progress_percent,
            event_sequence=job.event_sequence,
            heartbeat_status=(
                "stale"
                if job.status == "running"
                and (job.lease_expires_at is None or is_expired(job.lease_expires_at))
                else "active"
                if job.status == "running"
                else "not_applicable"
            ),
            issues=issues,
            error_code=job.error_code,
        )

    @staticmethod
    def _get_owned_job(db: Session, *, user_id: str, job_id: str) -> ReviewJob:
        job = db.get(ReviewJob, job_id)
        if job is None or job.user_id != user_id:
            raise ServiceError("review_job_not_found", "审核任务不存在。", 404)
        return job

    @staticmethod
    def _record_event(db: Session, job: ReviewJob, kind: str) -> ReviewJobEvent:
        job.event_sequence += 1
        event = ReviewJobEvent(
            job_id=job.job_id,
            sequence=job.event_sequence,
            kind=kind,
            completed_batches=job.completed_batches,
        )
        db.add(event)
        return event

    def _estimated_usage(
        self,
        batch: ServerReviewBatch,
        model: ModelDefinition,
    ) -> NormalizedUsage:
        request_payload = self.agent.request_payload(batch)
        serialized = json.dumps(request_payload, ensure_ascii=False, separators=(",", ":"))
        return NormalizedUsage(
            input_tokens=max(len(serialized.encode("utf-8")), 1),
            output_tokens=model.max_output_tokens,
        )


def _canonical_context(payload: ReviewJobCreateRequest) -> str:
    return json.dumps(
        payload.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
