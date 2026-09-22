"""S6-02 ReviewJobExecutor 优雅关闭（先红后绿）。

验收（总任务书 S6-02）：
1. 停止接收新任务；2. 设置 shutdown 状态；3. 等待 worker 到安全检查点；
4. 超时后标记 unknown/reconciliation；5. 再结束线程池。
"""
from __future__ import annotations

import contextlib
import threading
import time

from sqlalchemy import select

from asset_based_agent.report_review_server.models import ReviewJob, utc_now
from asset_based_agent.report_review_server.services.review_job_executor import (
    ReviewJobExecutor,
)
from asset_based_agent.report_review_server.services.review_job_service import (
    ReviewJobService,
)

from .test_review_jobs import FakeProviderClient, _job_payload, _seed_review_case


class FakeService:
    def __init__(self, gate=None):
        self.gate = gate
        self.executed = []
        self.requeued = []

    def execute_job(self, db, *, user_id, job_id, worker_id):
        if self.gate is not None:
            self.gate.wait(10)
        self.executed.append(job_id)

    def fail_requested_job(self, db, *, user_id, job_id, error_code):
        raise AssertionError('本测试不应走到 fail_requested_job')

    def recover_interrupted(self, db):
        return []

    def requeue_for_shutdown(self, db, *, worker_id, job_ids, error_code):
        self.requeued.append((worker_id, tuple(sorted(job_ids)), error_code))


def make_executor(service):
    return ReviewJobExecutor(lambda: contextlib.nullcontext(None), service)


def test_shutdown_waits_for_worker_safe_checkpoint():
    """活跃 job 在宽限期内完成：正常等待，不标记对账，池随后关闭。"""
    service = FakeService()
    executor = make_executor(service)
    assert executor.submit('u', 'job-fast') is True
    start = time.monotonic()
    executor.shutdown(timeout=5.0)
    assert time.monotonic() - start < 5.0
    assert service.executed == ['job-fast']
    assert service.requeued == []
    # shutdown 状态已设置：拒绝新任务
    assert executor.submit('u', 'job-late') is False


def test_shutdown_timeout_marks_running_jobs_for_reconciliation():
    """宽限期耗尽：仍运行的 job 必须被标记 requeue/对账，线程池照样关闭。"""
    gate = threading.Event()
    service = FakeService(gate)
    executor = make_executor(service)
    assert executor.submit('u', 'job-slow') is True
    deadline = time.monotonic() + 5
    while not service.executed and not gate.is_set():
        # 等 worker 真正进入 execute_job（gate.wait 阻塞中）
        if time.monotonic() > deadline:
            raise AssertionError('worker 未及时进入 execute_job')
        time.sleep(0.01)
        break
    time.sleep(0.2)
    executor.shutdown(timeout=0.3)
    assert service.requeued == [
        (executor.worker_id, ('job-slow',), 'shutdown_grace_expired')]
    assert executor.submit('u', 'job-after') is False
    gate.set()  # 放行 worker 线程收尾，避免泄漏
    executor.wait('job-slow', timeout=5)


def test_requeue_for_shutdown_only_touches_own_running_jobs(client):
    """服务层：只把本 worker 的 running job 重新排队，他人与终态不受影响。"""
    user_id, model_id = _seed_review_case(client)
    service = ReviewJobService(client.app.state.settings, FakeProviderClient([]))
    with client.app.state.session_factory() as db:
        mine = service.create_job(
            db, user_id=user_id,
            payload=_job_payload(model_id).model_copy(
                update={'client_job_id': 'S6-MINE'}))
        other = service.create_job(
            db, user_id=user_id,
            payload=_job_payload(model_id).model_copy(
                update={'client_job_id': 'S6-OTHER'}))
        done = service.create_job(
            db, user_id=user_id,
            payload=_job_payload(model_id).model_copy(
                update={'client_job_id': 'S6-DONE'}))
        for row, status, worker in (
                (db.get(ReviewJob, mine.job_id), 'running', 'proc-a'),
                (db.get(ReviewJob, other.job_id), 'running', 'proc-b'),
                (db.get(ReviewJob, done.job_id), 'succeeded', 'proc-a')):
            row.status = status
            row.worker_id = worker
            row.started_at = utc_now()
        db.commit()
        service.requeue_for_shutdown(
            db, worker_id='proc-a', job_ids=(mine.job_id, done.job_id),
            error_code='shutdown_grace_expired')
        mine_row = db.get(ReviewJob, mine.job_id)
        assert mine_row.status == 'queued'
        assert mine_row.error_code == 'shutdown_grace_expired'
        assert mine_row.worker_id is None
        assert mine_row.started_at is None
        # 其他 worker 的 running job 不动
        other_row = db.get(ReviewJob, other.job_id)
        assert other_row.status == 'running'
        assert other_row.worker_id == 'proc-b'
        # 终态 job 即使被误传入也不动
        done_row = db.get(ReviewJob, done.job_id)
        assert done_row.status == 'succeeded'
        events = list(db.scalars(select(ReviewJob).where(
            ReviewJob.job_id == mine.job_id)))
        assert events  # sanity：行仍在
