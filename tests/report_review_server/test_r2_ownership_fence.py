"""二次整改项1：ReviewJob ownership fence（先红后绿）。

验收（施工清单 1.6）：
- 旧 worker 活着（lease 未过期）时，新 worker 不能 claim；
- 旧 worker ownership 失效后，所有后续写操作（progress/result/terminal/hold 结算）被拒绝；
- shutdown 超时不得把 live job 变回可 claim 的 queued；
- 重复执行不得重复结算 hold；
- 滚动重启不得双执行同一 ReviewJob。
"""
from __future__ import annotations

import threading
import time
from datetime import timedelta

import pytest
from sqlalchemy import select

from asset_based_agent.report_review_server.models import (
    BalanceHold,
    ReviewJob,
    utc_now,
)
from asset_based_agent.report_review_server.services.auth_service import (
    ServiceError,
    is_expired,
)
from asset_based_agent.report_review_server.services.review_job_executor import (
    ReviewJobExecutor,
)
from asset_based_agent.report_review_server.services.review_job_service import (
    OwnershipLost,
    ReviewJobService,
)

from .test_review_jobs import (
    FakeProviderClient,
    _job_payload,
    _model_response,
    _seed_review_case,
)


class GatedProvider(FakeProviderClient):
    """provider 调用先阻塞在门闩上——模拟旧 worker 卡在 provider 调用中。"""

    def __init__(self, responses, *, gate: threading.Event, entered: threading.Event):
        super().__init__(responses)
        self._gate = gate
        self._entered = entered

    def call(self, route, payload):
        self._entered.set()
        assert self._gate.wait(10), '测试门闩超时未放行'
        return super().call(route, payload)


def _run_worker(service, session_factory, user_id, job_id, worker_id, errors):
    with session_factory() as db:
        try:
            service.execute_job(db, user_id=user_id, job_id=job_id, worker_id=worker_id)
        except BaseException as exc:  # noqa: BLE001 - 测试需要捕获线程内异常
            errors.append(exc)


def test_shutdown_timeout_does_not_make_live_job_claimable(client):
    """shutdown 宽限期耗尽后：live job 保持 running，新进程不得 claim。"""
    user_id, model_id = _seed_review_case(client)
    session_factory = client.app.state.session_factory
    settings = client.app.state.settings
    gate, entered = threading.Event(), threading.Event()
    provider = GatedProvider(
        [_model_response(1), _model_response(2)], gate=gate, entered=entered)
    service = ReviewJobService(settings, provider)
    executor_a = ReviewJobExecutor(session_factory, service)
    with session_factory() as db:
        job = service.create_job(db, user_id=user_id, payload=_job_payload(model_id))
    assert executor_a.submit(user_id, job.job_id) is True
    assert entered.wait(5), '旧 worker 未及时进入 provider 调用'

    executor_a.shutdown(timeout=0.3)  # 宽限期耗尽 → 触发 shutdown 兜底
    try:
        with session_factory() as db:
            row = db.get(ReviewJob, job.job_id)
            # 新语义：live job 不得变回 queued，ownership 标记保留
            assert row.status == 'running'
            assert row.worker_id == executor_a.worker_id
            assert row.lease_expires_at is not None
            assert not is_expired(row.lease_expires_at)
            assert row.error_code == 'shutdown_grace_expired'
        # 新进程 recover 不得捞走 lease 仍活的 job
        executor_b = ReviewJobExecutor(session_factory, service)
        assert executor_b.recover() == 0
        # 新 worker 直接 claim 也必须被拒绝
        with session_factory() as db:
            with pytest.raises(ServiceError) as excinfo:
                service.execute_job(
                    db, user_id=user_id, job_id=job.job_id, worker_id='proc-b')
            assert excinfo.value.code == 'review_job_in_progress'
    finally:
        gate.set()  # 放行旧 worker 线程收尾，避免泄漏


def test_old_worker_cannot_commit_after_ownership_lost(client):
    """ownership 被剥夺后：旧 worker 的后续写全部被 fence 拒绝。"""
    user_id, model_id = _seed_review_case(client)
    session_factory = client.app.state.session_factory
    settings = client.app.state.settings
    gate, entered = threading.Event(), threading.Event()
    provider = GatedProvider(
        [_model_response(1), _model_response(2)], gate=gate, entered=entered)
    service = ReviewJobService(settings, provider)
    with session_factory() as db:
        job = service.create_job(db, user_id=user_id, payload=_job_payload(model_id))

    errors: list[BaseException] = []
    thread = threading.Thread(
        target=_run_worker,
        args=(service, session_factory, user_id, job.job_id, 'proc-old', errors),
    )
    thread.start()
    assert entered.wait(5), '旧 worker 未及时进入 provider 调用'
    # 模拟 shutdown 兜底剥夺 ownership
    with session_factory() as db:
        service.requeue_for_shutdown(db, worker_id='proc-old', job_ids=(job.job_id,))
    gate.set()
    thread.join(10)
    assert not thread.is_alive(), '旧 worker 线程未退出'

    assert len(errors) == 1
    assert isinstance(errors[0], OwnershipLost)
    with session_factory() as db:
        row = db.get(ReviewJob, job.job_id)
        assert row.status == 'running'                 # 旧 worker 不得写 terminal
        assert row.error_code == 'shutdown_grace_expired'
        assert row.result_ciphertext is None           # 旧 worker 不得写 result
        assert row.progress_percent == 0               # 旧 worker 不得写 progress
        hold = db.get(BalanceHold, row.hold_id)
        assert hold.status == 'active'                 # 旧 worker 不得结算 hold


def test_new_worker_can_claim_only_after_old_lease_expires(client):
    """live lease 期间新 worker 不能 claim；lease 过期后 recover 重排才可执行。"""
    user_id, model_id = _seed_review_case(client)
    session_factory = client.app.state.session_factory
    settings = client.app.state.settings
    provider = FakeProviderClient([_model_response(1), _model_response(2)])
    service = ReviewJobService(settings, provider)
    with session_factory() as db:
        job = service.create_job(db, user_id=user_id, payload=_job_payload(model_id))
        service.request_execution(db, user_id=user_id, job_id=job.job_id)
        # 模拟 proc-a 持有的 live running job
        row = db.get(ReviewJob, job.job_id)
        row.status = 'running'
        row.worker_id = 'proc-a'
        row.claim_token = 'token-a'
        row.started_at = utc_now()
        row.lease_expires_at = utc_now() + timedelta(minutes=15)
        db.commit()

        # live lease：recover 不得重排
        assert service.recover_interrupted(db) == []
        row = db.get(ReviewJob, job.job_id)
        assert row.status == 'running'
        assert row.worker_id == 'proc-a'
        # 新 worker 直接 claim 被拒
        with pytest.raises(ServiceError):
            service.execute_job(
                db, user_id=user_id, job_id=job.job_id, worker_id='proc-b')

        # lease 过期后：recover 重排为 queued，清理 ownership 标记
        row = db.get(ReviewJob, job.job_id)
        row.lease_expires_at = utc_now() - timedelta(seconds=1)
        db.commit()
        assert service.recover_interrupted(db) == [(user_id, job.job_id)]
        row = db.get(ReviewJob, job.job_id)
        assert row.status == 'queued'
        assert row.worker_id is None
        assert row.claim_token is None

        # 新 worker 现在可以 claim 并执行成功
        result = service.execute_job(
            db, user_id=user_id, job_id=job.job_id, worker_id='proc-b')
        assert result.status == 'succeeded'
        assert len(provider.payloads) == 2
        row = db.get(ReviewJob, job.job_id)
        assert row.claim_token is None  # 终态必须清理 ownership 标记


def test_duplicate_execution_cannot_settle_hold_twice(client):
    """旧 worker 被 fence 后新 worker 重跑：hold 只结算一次。"""
    user_id, model_id = _seed_review_case(client)
    session_factory = client.app.state.session_factory
    settings = client.app.state.settings
    gate, entered = threading.Event(), threading.Event()
    provider = GatedProvider(
        [_model_response(1), _model_response(2)], gate=gate, entered=entered)
    service = ReviewJobService(settings, provider)
    with session_factory() as db:
        job = service.create_job(db, user_id=user_id, payload=_job_payload(model_id))

    errors: list[BaseException] = []
    thread = threading.Thread(
        target=_run_worker,
        args=(service, session_factory, user_id, job.job_id, 'proc-old', errors),
    )
    thread.start()
    assert entered.wait(5)
    with session_factory() as db:
        service.requeue_for_shutdown(db, worker_id='proc-old', job_ids=(job.job_id,))
    gate.set()
    thread.join(10)
    assert errors and isinstance(errors[0], OwnershipLost)

    with session_factory() as db:
        row = db.get(ReviewJob, job.job_id)
        hold = db.get(BalanceHold, row.hold_id)
        assert hold.status == 'active'  # 旧 worker 未结算
        # lease 过期 → 新 worker 重跑至成功
        row.lease_expires_at = utc_now() - timedelta(seconds=1)
        db.commit()
        assert service.recover_interrupted(db) == [(user_id, job.job_id)]
        result = service.execute_job(
            db, user_id=user_id, job_id=job.job_id, worker_id='proc-new')
        assert result.status == 'succeeded'

    # batch1 计费按 client_request_id 幂等重放：provider 总共只被调 2 次
    assert len(provider.payloads) == 2
    with session_factory() as db:
        holds = list(db.scalars(select(BalanceHold)))
        assert len(holds) == 1
        assert holds[0].status == 'captured'


def test_rolling_restart_does_not_double_execute_review_job(client):
    """滚动重启：旧进程 shutdown 兜底后，新进程只能在 lease 过期后接管一次。"""
    user_id, model_id = _seed_review_case(client)
    session_factory = client.app.state.session_factory
    settings = client.app.state.settings
    gate, entered = threading.Event(), threading.Event()
    provider_a = GatedProvider([_model_response(1)], gate=gate, entered=entered)
    provider_b = FakeProviderClient([_model_response(2)])
    service_a = ReviewJobService(settings, provider_a)
    service_b = ReviewJobService(settings, provider_b)
    executor_a = ReviewJobExecutor(session_factory, service_a)
    with session_factory() as db:
        job = service_a.create_job(db, user_id=user_id, payload=_job_payload(model_id))
    assert executor_a.submit(user_id, job.job_id) is True
    assert entered.wait(5)

    executor_a.shutdown(timeout=0.3)  # 旧进程关闭：宽限期耗尽
    # 新进程启动：live lease 期间 recover 不得捞取
    executor_b = ReviewJobExecutor(session_factory, service_b)
    assert executor_b.recover() == 0
    assert not provider_b.payloads

    gate.set()  # 旧 worker 收尾：OwnershipLost 必须被 executor 吞掉（不写 failed）
    executor_a.wait(job.job_id, timeout=10)  # 等旧 worker 线程结束再动库（共享连接）
    with session_factory() as db:
        row = db.get(ReviewJob, job.job_id)
        row.lease_expires_at = utc_now() - timedelta(seconds=1)
        db.commit()
    assert executor_b.recover() == 1  # lease 过期后新进程接管

    deadline = time.monotonic() + 15
    status = None
    while time.monotonic() < deadline:
        with session_factory() as db:
            status = db.get(ReviewJob, job.job_id).status
        if status in {'succeeded', 'failed'}:
            break
        time.sleep(0.05)
    assert status == 'succeeded'

    # batch1 幂等重放，新进程只真正调用 batch2
    assert len(provider_a.payloads) == 1
    assert len(provider_b.payloads) == 1
    with session_factory() as db:
        row = db.get(ReviewJob, job.job_id)
        assert row.status == 'succeeded'  # 旧进程不得写成 failed
        holds = list(db.scalars(select(BalanceHold)))
        assert len(holds) == 1
        assert holds[0].status == 'captured'
