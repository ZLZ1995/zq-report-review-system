"""S03 契约测试：InMemory 与 SQLite SessionRepo 必须满足同一行为契约。"""
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
def session(repo):
    repo.create_session('s1', project_id='p1', owner_id='alice', title='会话')
    return 's1'


# ------------------------------------------------------------------ 结构

def test_new_session_has_empty_main_lane(repo, session):
    assert repo.entries(session, 'main') == []


def test_entry_sequences_increase_and_form_parent_chain(repo, session):
    first = repo.begin_operation(session, 'main', user_text='一', request_id='r1')
    repo.complete_operation(first.id, assistant_entry_id=repo.append_entry(
        session, 'main', 'assistant_message', {'text': '答一'}).id, turn_id=None)
    repo.begin_operation(session, 'main', user_text='二', request_id='r2')
    entries = repo.entries(session, 'main')
    sequences = [e.sequence for e in entries]
    assert sequences == sorted(sequences) and len(set(sequences)) == len(sequences)
    parents = [e.parent_id for e in entries]
    assert parents[0] is None
    assert parents[1:] == [e.id for e in entries[:-1]]


# ------------------------------------------------------------------ operation 生命周期

def test_begin_operation_creates_user_entry_and_running_operation(repo, session):
    operation = repo.begin_operation(session, 'main', user_text='你好', request_id='r1')
    assert operation.status == 'running'
    assert operation.request_id == 'r1'
    entries = repo.entries(session, 'main')
    assert len(entries) == 1
    assert entries[0].entry_type == 'user_message'
    assert entries[0].payload['text'] == '你好'
    assert repo.get_operation(operation.id).source_entry_id == entries[0].id


def test_same_lane_second_begin_rejected(repo, session):
    from asset_based_agent.technical_platform.agent_core.errors import OperationBusy
    repo.begin_operation(session, 'main', user_text='一', request_id='r1')
    with pytest.raises(OperationBusy) as info:
        repo.begin_operation(session, 'main', user_text='二', request_id='r2')
    assert info.value.code == 'agent.operation_busy'


def test_different_lanes_accept_concurrent_operations(repo, session):
    repo.create_lane(session, 'side', name='side')
    first = repo.begin_operation(session, 'main', user_text='一', request_id='r1')
    second = repo.begin_operation(session, 'side', user_text='二', request_id='r2')
    assert first.id != second.id


def test_completed_operation_frees_the_lane(repo, session):
    operation = repo.begin_operation(session, 'main', user_text='一', request_id='r1')
    entry = repo.append_entry(session, 'main', 'assistant_message', {'text': '答'})
    repo.complete_operation(operation.id, assistant_entry_id=entry.id, turn_id=None)
    assert repo.get_operation(operation.id).status == 'completed'
    followup = repo.begin_operation(session, 'main', user_text='二', request_id='r2')
    assert followup.status == 'running'


def test_fail_operation_records_error_code_and_entry(repo, session):
    operation = repo.begin_operation(session, 'main', user_text='一', request_id='r1')
    repo.fail_operation(operation.id, code='model.timeout', summary='t', turn_id=None)
    record = repo.get_operation(operation.id)
    assert record.status == 'failed'
    assert record.error_code == 'model.timeout'
    last = repo.entries(session, 'main')[-1]
    assert last.entry_type == 'error_message'
    assert last.payload['error_code'] == 'model.timeout'


def test_abort_operation_records_cancelled_entry(repo, session):
    operation = repo.begin_operation(session, 'main', user_text='一', request_id='r1')
    repo.abort_operation(operation.id, turn_id=None)
    record = repo.get_operation(operation.id)
    assert record.status == 'aborted'
    assert repo.entries(session, 'main')[-1].entry_type == 'error_message'


def test_open_operations_lists_only_open(repo, session):
    first = repo.begin_operation(session, 'main', user_text='一', request_id='r1')
    assert [op.id for op in repo.open_operations(session)] == [first.id]
    repo.abort_operation(first.id, turn_id=None)
    assert repo.open_operations(session) == []


def test_invalid_operation_kind_leaves_no_partial_state(repo, session):
    with pytest.raises((ValueError, Exception)):  # 两实现异常类型均为 ValueError
        repo.begin_operation(session, 'main', user_text='一', request_id='r1',
                             kind='bogus-kind')
    assert repo.entries(session, 'main') == [], '失败不得留下半条消息'
    assert repo.open_operations(session) == []


# ------------------------------------------------------------------ 模型请求

def test_model_request_carries_history_in_order(repo, session):
    operation = repo.begin_operation(session, 'main', user_text='问一', request_id='r1')
    request = repo.build_model_request(operation)
    assert request.request_id == 'r1'
    assert request.messages[-1]['payload']['text'] == '问一'


# ------------------------------------------------------- S09 permission mode

def test_permission_mode_roundtrip(repo, session):
    assert repo.session_permission_mode(session) == 'full'
    for mode in ('request', 'assisted', 'full'):
        repo.set_permission_mode(session, mode)
        assert repo.session_permission_mode(session) == mode
    with pytest.raises(ValueError):
        repo.set_permission_mode(session, 'superuser')


def test_tool_call_authorization_id_roundtrip(repo, session):
    operation = repo.begin_operation(session, 'main', user_text='执行', request_id='r1')
    turn_id = repo.begin_turn(operation.id, 1, input_context_sha256='x')
    call_id = repo.begin_tool_call(operation.id, turn_id, name='probe',
                                   arguments={}, risk='local_readonly',
                                   idempotency_key='k1')
    assert repo.tool_calls(operation.id)[0].authorization_id is None
    repo.set_tool_call_authorization(call_id, 'receipt-1')
    assert repo.tool_calls(operation.id)[0].authorization_id == 'receipt-1'


# ------------------------------------------------- S10 facts/bindings/compaction

def test_session_project_id(repo, session):
    assert repo.session_project_id(session) == 'p1'


def test_fact_lifecycle_and_confirmed_filter(repo, session):
    proposed = repo.propose_fact('p1', 'project', '口径', '保守')
    assert repo.facts('p1', status='confirmed') == []
    repo.set_fact_status(proposed, 'confirmed')
    confirmed = repo.facts('p1', status='confirmed')
    assert len(confirmed) == 1 and confirmed[0]['fact_key'] == '口径'
    assert confirmed[0]['value'] == '保守'
    repo.set_fact_status(proposed, 'superseded')
    assert repo.facts('p1', status='confirmed') == []
    rejected = repo.propose_fact('p1', 'project', '猜测', 'X')
    repo.set_fact_status(rejected, 'rejected')
    with pytest.raises(ValueError):
        repo.set_fact_status(rejected, 'confirmed')  # rejected 终态不可回转


def test_fact_secret_values_are_rejected(repo, session):
    with pytest.raises(ValueError):
        repo.propose_fact('p1', 'project', '钥匙', 'token=abc12345')
    with pytest.raises(ValueError):
        repo.propose_fact('p1', 'project', '密码', {'password': 'pw123456'})


def test_file_bindings_default_scope_is_explicit_only(repo, session):
    operation = repo.begin_operation(session, 'main', user_text='执行', request_id='r1')
    repo.bind_file(operation.id, 'f1', 'explicit_upload', sha256='a' * 64)
    repo.bind_file(operation.id, 'f2', 'agent_discovered', sha256='b' * 64)
    repo.bind_file(operation.id, 'f3', 'explicit_mention', sha256='c' * 64)
    default = repo.operation_files(operation.id)
    assert {b['file_id'] for b in default} == {'f1', 'f3'}
    discovered = repo.operation_files(operation.id, kinds=('agent_discovered',))
    assert {b['file_id'] for b in discovered} == {'f2'}
    with pytest.raises(ValueError):
        repo.bind_file(operation.id, 'f4', '非法kind', sha256='d' * 64)


def test_compaction_save_and_latest(repo, session):
    first = repo.append_entry(session, 'main', 'user_message', {'text': '一'})
    second = repo.append_entry(session, 'main', 'context_summary', {'text': '摘要一'})
    third = repo.append_entry(session, 'main', 'context_summary', {'text': '摘要二'})
    repo.save_compaction(session, 'main', source_start_entry_id=first.id,
                         source_end_entry_id=first.id, source_sha256='a' * 64,
                         summary_entry_id=second.id)
    repo.save_compaction(session, 'main', source_start_entry_id=first.id,
                         source_end_entry_id=second.id, source_sha256='b' * 64,
                         summary_entry_id=third.id)
    latest = repo.latest_compaction(session, 'main')
    assert latest['summary_entry_id'] == third.id
    assert latest['source_sha256'] == 'b' * 64
    assert repo.latest_compaction(session, '别的lane') is None


def test_list_sessions_returns_owner_sessions(repo, session):
    repo.create_session('s2', project_id='p1', owner_id='alice', title='会话二')
    listed = repo.list_sessions()
    assert [s['id'] for s in listed] == ['s1', 's2']
    assert listed[0]['title'] == '会话'
    assert listed[0]['permission_mode'] == 'full'
