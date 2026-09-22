"""Process-local executor backed by persistent database task state.

The first production deployment intentionally runs one server replica. Database
claiming still prevents duplicate execution if the HTTP endpoint is repeated.
"""
from __future__ import annotations

import logging
import threading
import time
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError

logger = logging.getLogger(__name__)


class ReviewJobExecutor:
    def __init__(self, session_factory, service, *, max_workers: int = 1) -> None:
        self.session_factory = session_factory
        self.service = service
        self.worker_id = f"process-{uuid.uuid4()}"
        self._pool = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="review-job")
        self._lock = threading.Lock()
        self._futures: dict[str, Future] = {}
        self._shutting_down = False

    @property
    def shutting_down(self) -> bool:
        with self._lock:
            return self._shutting_down

    def replace_service(self, service) -> None:
        with self._lock:
            if any(not future.done() for future in self._futures.values()):
                raise RuntimeError("Cannot replace review service while a job is active")
            self.service = service

    def submit(self, user_id: str, job_id: str, *, service=None) -> bool:
        with self._lock:
            if self._shutting_down:
                return False  # S6-02：关闭开始后停止接收新任务
            current = self._futures.get(job_id)
            if current is not None and not current.done():
                return False
            try:
                future = self._pool.submit(self._run, service or self.service, user_id, job_id)
            except RuntimeError:
                return False  # 线程池已关闭
            self._futures[job_id] = future
        # 回调必须在锁外注册：future 已完成时 add_done_callback 会在调用线程
        # 同步执行回调，锁内注册会与 _forget 形成自死锁。
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
        if self.shutting_down:
            return 0  # 关闭流程中不再捞新任务
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

    def shutdown(self, *, timeout: float = 30.0) -> None:
        """S6-02 优雅关闭：

        1. 设置 shutdown 状态，停止接收新任务；
        2. 等待活跃 worker 到达安全检查点（自然完成）直到宽限期；
        3. 超时后把仍 running 的 job 重新排队标记 shutdown_grace_expired，
           留待下次启动 recover_interrupted 恢复；
        4. 最后结束线程池（cancel_futures 取消未开始的排队任务——它们从未
           在库中认领，恢复流程会重新调度）。
        """
        with self._lock:
            self._shutting_down = True
            active = [future for future in self._futures.values() if not future.done()]
        deadline = time.monotonic() + timeout
        for future in active:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            try:
                future.result(timeout=remaining)
            except (FutureTimeoutError, TimeoutError):
                break
            except Exception:  # job 自身失败已落库，不阻塞关闭
                logger.debug('关闭等待期间 job 自行失败（已落库），继续等待其余 worker',
                             exc_info=True)
        with self._lock:
            expired = tuple(
                job_id for job_id, future in self._futures.items()
                if not future.done())
        if expired:
            with self.session_factory() as db:
                self.service.requeue_for_shutdown(
                    db,
                    worker_id=self.worker_id,
                    job_ids=expired,
                    error_code="shutdown_grace_expired",
                )
        self._pool.shutdown(wait=False, cancel_futures=True)
