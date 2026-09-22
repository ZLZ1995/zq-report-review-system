"""S2-01 执行 Lease：双开客户端不得误杀活任务（先红后绿）。

规则（总任务书 S2-01）：
- worker 执行时周期刷新 lease；
- recover() 只能处理无 owner / lease 已过期 / owner 明确失效的 operation；
- lease 未过期时新请求必须 OperationBusy，不能 interrupt。
"""
import asyncio
import sqlite3

import pytest


def run(coro):
    return asyncio.run(coro)


def make_kernel(repo, *, scripts=(), executor_id=None, lease_seconds=15.0,
                heartbeat_interval=5.0, stream_factory=None):
    from asset_based_agent.technical_platform.agent_core.fakes import (
        FakeModelPort,
    )
    from asset_based_agent.technical_platform.agent_core.runtime import (
        AgentKernel,
    )
    if stream_factory is not None:
        model = FakeModelPort.from_stream_factory(stream_factory)
    else:
        model = FakeModelPort(list(scripts))
    return AgentKernel(repo=repo, model=model, executor_id=executor_id,
                       lease_seconds=lease_seconds,
                       heartbeat_interval=heartbeat_interval)


def memory_repo():
    from asset_based_agent.technical_platform.agent_core.fakes import (
        InMemorySessionRepo,
    )
    repo = InMemorySessionRepo()
    repo.create_session('s1', project_id='p1', owner_id='alice', title='会话')
    return repo


def sqlite_repo(tmp_path):
    from asset_based_agent.technical_platform.sessions.sqlite_repository import (
        SQLiteSessionRepo,
    )
    from asset_based_agent.technical_platform.store import PlatformStore
    PlatformStore(tmp_path / 'db.sqlite', 'alice')
    repo = SQLiteSessionRepo(tmp_path / 'db.sqlite', 'alice')
    repo.create_session('s1', project_id='p1', owner_id='alice', title='会话')
    return repo


# ------------------------------------------------------------------ recover 语义

def test_recover_does_not_interrupt_live_lease():
    repo = memory_repo()
    operation = repo.begin_operation(
        's1', 'main', user_text='问', request_id='r1',
        executor_id='proc-a', lease_seconds=300)
    kernel_b = make_kernel(repo, executor_id='proc-b')
    result = run(kernel_b.recover('s1'))
    assert result['interrupted'] == [], '活 lease 不得被 recover 收束'
    assert repo.get_operation(operation.id).status == 'running'


def test_expired_lease_can_transition_to_unknown():
    repo = memory_repo()
    operation = repo.begin_operation(
        's1', 'main', user_text='问', request_id='r1',
        executor_id='proc-a', lease_seconds=-1)  # 立即过期
    kernel_b = make_kernel(repo, executor_id='proc-b')
    result = run(kernel_b.recover('s1'))
    assert result['interrupted'] == [operation.id]
    assert repo.get_operation(operation.id).status == 'unknown'


def test_ownerless_operation_can_be_recovered():
    repo = memory_repo()
    operation = repo.begin_operation('s1', 'main', user_text='问',
                                     request_id='r1')
    kernel_b = make_kernel(repo, executor_id='proc-b')
    result = run(kernel_b.recover('s1'))
    assert result['interrupted'] == [operation.id]
    assert repo.get_operation(operation.id).status == 'unknown'


def test_second_process_cannot_steal_live_operation():
    from asset_based_agent.technical_platform.agent_core.errors import (
        OperationBusy,
    )
    repo = memory_repo()
    operation = repo.begin_operation(
        's1', 'main', user_text='问', request_id='r1',
        executor_id='proc-a', lease_seconds=300)
    kernel_b = make_kernel(repo, scripts=[], executor_id='proc-b')
    with pytest.raises(OperationBusy):
        run(kernel_b.submit('s1', 'main', {'text': '新请求'}))
    record = repo.get_operation(operation.id)
    assert record.status == 'running'
    assert record.executor_id == 'proc-a', '活 operation 的 owner 不得被改写'


def test_worker_heartbeat_refreshes_lease():
    repo = memory_repo()
    heartbeats = []
    original = repo.heartbeat_operation

    def spy(operation_id, executor_id, lease_seconds):
        heartbeats.append(operation_id)
        return original(operation_id, executor_id, lease_seconds)

    repo.heartbeat_operation = spy

    async def slow_stream(_request, _cancel):
        from asset_based_agent.technical_platform.agent_core.contracts import (
            ModelEvent,
        )
        yield ModelEvent('message_start', {})
        await asyncio.sleep(0.25)
        yield ModelEvent('text_delta', {'text': '慢回答'})
        yield ModelEvent('message_complete', {})

    kernel = make_kernel(repo, executor_id='proc-a', lease_seconds=10,
                         heartbeat_interval=0.05, stream_factory=slow_stream)
    accepted = run(kernel.submit('s1', 'main', {'text': '问'}))
    assert repo.get_operation(accepted.operation_id).status == 'completed'
    assert len(heartbeats) >= 2, 'worker 执行期间必须周期刷新 lease'


# ------------------------------------------------------------------ SQLite 持久化与迁移

def test_sqlite_begin_operation_persists_lease(tmp_path):
    repo = sqlite_repo(tmp_path)
    operation = repo.begin_operation(
        's1', 'main', user_text='问', request_id='r1',
        executor_id='proc-a', lease_seconds=60)
    record = repo.get_operation(operation.id)
    assert record.executor_id == 'proc-a'
    assert record.lease_expires_at, 'lease 过期时间必须持久化'
    assert record.last_heartbeat_at, '心跳时间必须持久化'


def test_v15_to_v16_migration_adds_lease_columns(tmp_path):
    from asset_based_agent.technical_platform.local_migrations import (
        migrate_database,
    )
    from asset_based_agent.technical_platform.store import PlatformStore
    path = tmp_path / 'db.sqlite'
    store = PlatformStore(path, 'alice')
    project = store.create_project('p')
    session = store.create_session(project)
    store.append(session, 'user', '历史消息')
    with sqlite3.connect(path) as db:
        db.execute('BEGIN IMMEDIATE')
        db.execute('ALTER TABLE agent_operations DROP COLUMN executor_id')
        db.execute('ALTER TABLE agent_operations DROP COLUMN lease_expires_at')
        db.execute('ALTER TABLE agent_operations DROP COLUMN last_heartbeat_at')
        db.execute('PRAGMA user_version=15')
        db.commit()
    backup = migrate_database(path)
    assert backup is not None and backup.is_file()
    with sqlite3.connect(path) as db:
        assert db.execute('PRAGMA user_version').fetchone()[0] == 16
        columns = {row[1] for row in db.execute(
            'PRAGMA table_info(agent_operations)')}
        assert {'executor_id', 'lease_expires_at',
                'last_heartbeat_at'} <= columns
        texts = [row[0] for row in db.execute('SELECT text FROM messages')]
    assert texts == ['历史消息'], '迁移不得改写旧消息'
