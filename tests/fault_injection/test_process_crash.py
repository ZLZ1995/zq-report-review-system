"""S8-04 故障注入：进程崩溃（process crash）。

注入：worker 进程崩溃 → operation 残留 running 但 lease 过期 →
另一进程 recover() 必须将其收束为 unknown，不得继续当作活任务，
也不得重复收束。
"""
from __future__ import annotations

import asyncio


def _run(coro):
    return asyncio.run(coro)


def _make_kernel(repo, *, executor_id):
    from asset_based_agent.technical_platform.agent_core.fakes import (
        FakeModelPort,
    )
    from asset_based_agent.technical_platform.agent_core.runtime import (
        AgentKernel,
    )
    return AgentKernel(repo=repo, model=FakeModelPort([]),
                       executor_id=executor_id)


def _memory_repo():
    from asset_based_agent.technical_platform.agent_core.fakes import (
        InMemorySessionRepo,
    )
    repo = InMemorySessionRepo()
    repo.create_session('s1', project_id='p1', owner_id='alice', title='会话')
    return repo


def test_crashed_worker_operation_recovers_to_unknown():
    repo = _memory_repo()
    # proc-a 崩溃现场：operation 仍在 running，lease 已过期（lease_seconds=-1）
    operation = repo.begin_operation(
        's1', 'main', user_text='问', request_id='r1',
        executor_id='proc-a', lease_seconds=-1)
    # proc-b 启动后执行崩溃恢复
    kernel_b = _make_kernel(repo, executor_id='proc-b')
    result = _run(kernel_b.recover('s1'))
    assert result['interrupted'] == [operation.id]
    recovered = repo.get_operation(operation.id)
    assert recovered.status == 'unknown', '崩溃残留必须收束为 unknown'
    # 恢复幂等：再次 recover 不得重复收束
    again = _run(kernel_b.recover('s1'))
    assert again['interrupted'] == []
    assert repo.get_operation(operation.id).status == 'unknown'
