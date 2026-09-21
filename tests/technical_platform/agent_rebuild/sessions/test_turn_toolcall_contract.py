"""S05 契约测试：Turn/ToolCall/事件持久化与中断恢复（memory/sqlite 双实现）。"""
import pytest


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
    store = PlatformStore(tmp_path / 'db.sqlite', 'alice')
    return SQLiteSessionRepo(store.path, 'alice')


@pytest.fixture(params=['memory', 'sqlite'])
def repo(request, tmp_path):
    return _memory_repo(tmp_path) if request.param == 'memory' else _sqlite_repo(tmp_path)


@pytest.fixture()
def operation(repo):
    repo.create_session('s1', project_id='p1', owner_id='alice', title='会话')
    return repo.begin_operation('s1', 'main', user_text='一', request_id='r1')


# ------------------------------------------------------------------ turn

def test_turn_lifecycle_round_trip(repo, operation):
    turn_id = repo.begin_turn(operation.id, 1, input_context_sha256='a' * 64,
                              model_request_id='req-1')
    repo.finish_turn(turn_id, 'completed', assistant_entry_id=None,
                     usage={'input_tokens': 3})
    turns = repo.turns(operation.id)
    assert len(turns) == 1
    assert turns[0].ordinal == 1
    assert turns[0].status == 'completed'
    assert turns[0].usage == {'input_tokens': 3}
    assert turns[0].input_context_sha256 == 'a' * 64


def test_turns_ordered_by_ordinal(repo, operation):
    first = repo.begin_turn(operation.id, 1, input_context_sha256='a' * 64)
    repo.finish_turn(first, 'completed')
    second = repo.begin_turn(operation.id, 2, input_context_sha256='b' * 64)
    repo.finish_turn(second, 'failed', error_code='model.timeout')
    turns = repo.turns(operation.id)
    assert [t.ordinal for t in turns] == [1, 2]
    assert turns[1].status == 'failed'
    assert turns[1].error_code == 'model.timeout'


# ------------------------------------------------------------------ tool call

def test_tool_call_lifecycle_round_trip(repo, operation):
    turn_id = repo.begin_turn(operation.id, 1, input_context_sha256='a' * 64)
    call_id = repo.begin_tool_call(
        operation.id, turn_id, name='read_file', arguments={'path': 'a.txt'},
        risk='local_readonly', idempotency_key='k-1')
    repo.finish_tool_call(call_id, 'succeeded', result_entry_id=None)
    calls = repo.tool_calls(operation.id)
    assert len(calls) == 1
    assert calls[0].tool_name == 'read_file'
    assert calls[0].status == 'succeeded'
    assert calls[0].arguments == {'path': 'a.txt'}
    assert calls[0].arguments_sha256
    assert calls[0].risk_level == 'local_readonly'


def test_tool_call_idempotency_key_unique(repo, operation):
    turn_id = repo.begin_turn(operation.id, 1, input_context_sha256='a' * 64)
    repo.begin_tool_call(operation.id, turn_id, name='t', arguments={},
                         risk='local_readonly', idempotency_key='dup')
    with pytest.raises(Exception, match='(?i)idempot|unique|重复'):
        repo.begin_tool_call(operation.id, turn_id, name='t', arguments={},
                             risk='local_readonly', idempotency_key='dup')


# ------------------------------------------------------------------ events

def test_recorded_events_persist_in_order(repo, operation):
    repo.record_event('s1', 'main', 'turn_started', operation_id=operation.id,
                      turn_id='t1', payload={'ordinal': 1})
    repo.record_event('s1', 'main', 'tool_started', operation_id=operation.id,
                      turn_id='t1', tool_call_id='c1', payload={'name': 'x'})
    events = repo.persisted_events('s1')
    kinds = [e['event_type'] for e in events]
    assert kinds[:1] == ['operation_accepted'], 'begin_operation 已落首事件'
    assert kinds[1:] == ['turn_started', 'tool_started']
    assert events[2]['tool_call_id'] == 'c1'


# ------------------------------------------------------------------ interrupt

def test_interrupt_operation_closes_everything_open(repo, operation):
    turn_id = repo.begin_turn(operation.id, 1, input_context_sha256='a' * 64)
    repo.begin_tool_call(
        operation.id, turn_id, name='upload', arguments={'f': 1},
        risk='external_upload', idempotency_key='k-up')
    repo.interrupt_operation(operation.id, code='agent.interrupted',
                             summary='进程中断')
    record = repo.get_operation(operation.id)
    assert record.status == 'unknown'
    assert record.error_code == 'agent.interrupted'
    assert repo.open_operations('s1') == []
    # 用户可见的错误 Entry
    last = repo.entries('s1', 'main')[-1]
    assert last.entry_type == 'error_message'
    # 未闭合 turn 与 tool call 一并收束为 unknown
    assert repo.turns(operation.id)[0].status == 'unknown'
    assert repo.tool_calls(operation.id)[0].status == 'unknown'
    # 终态事件已持久化
    kinds = [e['event_type'] for e in repo.persisted_events('s1')]
    assert kinds[-1] == 'operation_unknown'
