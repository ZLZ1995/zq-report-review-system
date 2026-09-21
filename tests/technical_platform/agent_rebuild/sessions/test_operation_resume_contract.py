"""S07 契约测试：资源快照与 operation 恢复（memory/sqlite 双实现）。"""
import pytest

SNAPSHOT = [{'id': 'probe-skill', 'version': '1.0.0', 'sha256': 'ab12',
             'source': 'user'}]


def _memory_repo(tmp_path):
    from asset_based_agent.technical_platform.agent_core.fakes import (
        InMemorySessionRepo,
    )
    return InMemorySessionRepo()


def _sqlite_repo(tmp_path):
    from asset_based_agent.technical_platform.sessions.sqlite_repository import (
        SQLiteSessionRepo,
    )
    from asset_based_agent.technical_platform.store import PlatformStore
    PlatformStore(tmp_path / 'db.sqlite', 'alice')
    return SQLiteSessionRepo(tmp_path / 'db.sqlite', 'alice')


@pytest.fixture(params=['memory', 'sqlite'])
def repo(request, tmp_path):
    if request.param == 'memory':
        return _memory_repo(tmp_path)
    return _sqlite_repo(tmp_path)


@pytest.fixture()
def operation(repo):
    repo.create_session('s1', project_id='p1', owner_id='alice', title='会话')
    return repo.begin_operation('s1', 'main', user_text='一', request_id='r1')


# ------------------------------------------------------------- 资源快照

def test_resource_snapshot_round_trip(repo, operation):
    repo.set_resource_snapshot(operation.id, SNAPSHOT)
    assert repo.resource_snapshot(operation.id) == SNAPSHOT


def test_resource_snapshot_defaults_empty(repo, operation):
    assert repo.resource_snapshot(operation.id) == []


def test_sqlite_snapshot_survives_reopen(tmp_path):
    repo_a = _sqlite_repo(tmp_path)
    repo_a.create_session('s1', project_id='p1', owner_id='alice', title='会话')
    operation = repo_a.begin_operation('s1', 'main', user_text='一',
                                       request_id='r1')
    repo_a.set_resource_snapshot(operation.id, SNAPSHOT)
    repo_b = _sqlite_repo(tmp_path)
    assert repo_b.resource_snapshot(operation.id) == SNAPSHOT, \
        '资源快照必须随库持久化，重启后可用于按原版本恢复'


# ------------------------------------------------------------- 恢复

def test_resume_operation_reopens_unknown(repo, operation):
    repo.interrupt_operation(operation.id, code='agent.interrupted',
                             summary='进程中断')
    repo.resume_operation(operation.id)
    record = repo.get_operation(operation.id)
    assert record.status == 'running'
    assert record.finished_at is None
    assert record.error_code is None
    kinds = [e['event_type'] for e in repo.persisted_events('s1')]
    assert kinds[-1] == 'operation_resumed'


def test_resume_operation_rejects_non_unknown(repo, operation):
    with pytest.raises(ValueError):
        repo.resume_operation(operation.id)  # running
    repo.interrupt_operation(operation.id, code='agent.interrupted',
                             summary='进程中断')
    repo.resume_operation(operation.id)
    repo.complete_operation(operation.id, assistant_entry_id=None,
                            turn_id=None)
    with pytest.raises(ValueError):
        repo.resume_operation(operation.id)  # completed
