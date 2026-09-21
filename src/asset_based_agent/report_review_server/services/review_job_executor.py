"""Process-local executor backed by persistent database task state.

The first production deployment intentionally runs one server replica. Database
claiming still prevents duplicate execution if the HTTP endpoint is repeated.
"""
from __future__ import annotations

import threading
import uuid
from concurrent.futures import Future, ThreadPoolExecutor


class ReviewJobExecutor:
    def __init__(self, session_factory, service, *, max_workers: int = 1) -> None:
        self.session_factory = session_factory
        self.service = service
        self.worker_id = f"process-{uuid.uuid4()}"
        self._pool = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="review-job")
        self._lock = threading.Lock()
        self._futures: dict[str, Future] = {}

    def replace_service(self, service) -> None:
        with self._lock:
            if any(not future.done() for future in self._futures.values()):
                raise RuntimeError("Cannot replace review service while a job is active")
            self.service = service

    def submit(self, user_id: str, job_id: str, *, service=None) -> bool:
        with self._lock:
            current = self._futures.get(job_id)
            if current is not None and not current.done():
                return False
            future = self._pool.submit(self._run, service or self.service, user_id, job_id)
            self._futures[job_id] = future
            future.add_done_callback(lambda completed: self._forget(job_id, completed))
            return True

    def _forget(self, job_id: str, completed: Future) -> None:
        with self._lock:
            if self._futures.get(job_id) is completed:
                self._futures.pop(job_id, None)

    def _run(self, service, user_id: str, job_id: str) -> None:
        with self.session_factory() as db:
            try:
                service.execute_job(
                    db,
                    user_id=user_id,
                    job_id=job_id,
                    worker_id=self.worker_id,
                )
            except Exception as exc:  # noqa: BLE001 - persist only a safe public code
                # Provider-call failures are persisted inside execute_job. This
                # fallback closes preflight failures that happen before the
                # queued job is claimed, without copying exception text.
                db.rollback()
                service.fail_requested_job(
                    db,
                    user_id=user_id,
                    job_id=job_id,
                    error_code=getattr(exc, "code", "review_execution_rejected"),
                )
                return

    def recover(self) -> int:
        with self.session_factory() as db:
            jobs = self.service.recover_interrupted(db)
        for user_id, job_id in jobs:
            self.submit(user_id, job_id, service=self.service)
        return len(jobs)

    def wait(self, job_id: str, *, timeout: float | None = None) -> bool:
        with self._lock:
            future = self._futures.get(job_id)
        if future is None:
            return True
        future.result(timeout=timeout)
        return True

    def shutdown(self) -> None:
        self._pool.shutdown(wait=False, cancel_futures=False)
