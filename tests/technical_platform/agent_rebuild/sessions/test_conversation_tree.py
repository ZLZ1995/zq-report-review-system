"""S04 契约测试：Conversation Tree——分支共享父链、有界查询、lane 删除。

InMemory 与 SQLite 实现必须通过同一组契约。
"""
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
def anchor(repo):
    """main lane 两条消息后的 assistant entry，作为分支锚点。"""
    repo.create_session('s1', project_id='p1', owner_id='alice', title='会话')
    operation = repo.begin_operation('s1', 'main', user_text='一', request_id='r1')
    reply = repo.append_entry('s1', 'main', 'assistant_message', {'text': '答一'})
    repo.complete_operation(operation.id, assistant_entry_id=reply.id, turn_id=None)
    return reply


# ------------------------------------------------------------------ 分支

def test_branch_shares_parent_chain_without_copying_entries(repo, anchor):
    repo.create_lane('s1', 'side', name='side', anchor_entry_id=anchor.id)
    repo.begin_operation('s1', 'side', user_text='分支问题', request_id='r2')
    history = repo.lane_history('s1', 'side')
    assert [e.entry_type for e in history] == [
        'user_message', 'assistant_message', 'user_message']
    assert [e.payload['text'] for e in history] == ['一', '答一', '分支问题']
    # 创建分支不复制 Entry：main 仍 2 条，side 只有自己的 1 条
    assert len(repo.entries('s1', 'main')) == 2
    assert len(repo.entries('s1', 'side')) == 1
    # main 的父链不受分支影响
    main_history = repo.lane_history('s1', 'main')
    assert [e.payload['text'] for e in main_history] == ['一', '答一']


def test_lane_history_is_bounded(repo, anchor):
    repo.create_lane('s1', 'side', name='side', anchor_entry_id=anchor.id)
    repo.begin_operation('s1', 'side', user_text='分支一', request_id='r2')
    repo.append_entry('s1', 'side', 'assistant_message', {'text': '分支答一'})
    history = repo.lane_history('s1', 'side', limit=2)
    assert [e.payload['text'] for e in history] == ['分支一', '分支答一']
    full = repo.lane_history('s1', 'side')
    assert len(full) == 4


def test_tree_projection_lists_lanes_with_counts(repo, anchor):
    repo.create_lane('s1', 'side', name='side', anchor_entry_id=anchor.id)
    tree = repo.tree('s1')
    lanes = {lane['id']: lane for lane in tree['lanes']}
    assert lanes['main']['entry_count'] == 2
    assert lanes['side']['entry_count'] == 0
    assert lanes['side']['anchor_entry_id'] == anchor.id
    assert lanes['side']['parent_lane_id'] is None


def test_nested_branch_chains_through_parent_lane(repo, anchor):
    repo.create_lane('s1', 'side', name='side', anchor_entry_id=anchor.id)
    operation = repo.begin_operation('s1', 'side', user_text='分支一', request_id='r2')
    side_entry = repo.append_entry(
        's1', 'side', 'assistant_message', {'text': '分支答一'})
    repo.complete_operation(operation.id, assistant_entry_id=side_entry.id,
                            turn_id=None)
    repo.create_lane('s1', 'grand', name='grand', parent_lane_id='side',
                     anchor_entry_id=side_entry.id)
    repo.begin_operation('s1', 'grand', user_text='孙分支', request_id='r3')
    history = repo.lane_history('s1', 'grand')
    assert [e.payload['text'] for e in history] == [
        '一', '答一', '分支一', '分支答一', '孙分支']


# ------------------------------------------------------------------ 删除

def test_delete_lane_removes_only_branch_entries(repo, anchor):
    repo.create_lane('s1', 'side', name='side', anchor_entry_id=anchor.id)
    repo.append_entry('s1', 'side', 'system_note', {'text': '分支批注'})
    repo.delete_lane('s1', 'side')
    assert repo.entries('s1', 'side') == []
    assert [e.payload['text'] for e in repo.lane_history('s1', 'main')] == [
        '一', '答一']
    lanes = {lane['id'] for lane in repo.tree('s1')['lanes']}
    assert lanes == {'main'}


def test_delete_lane_with_closed_operation_refused(repo, anchor):
    repo.create_lane('s1', 'side', name='side', anchor_entry_id=anchor.id)
    operation = repo.begin_operation('s1', 'side', user_text='分支一', request_id='r2')
    repo.abort_operation(operation.id, turn_id=None)
    with pytest.raises(ValueError, match='操作历史'):
        repo.delete_lane('s1', 'side')


def test_delete_main_lane_refused(repo, anchor):
    with pytest.raises(ValueError, match='main'):
        repo.delete_lane('s1', 'main')


def test_delete_lane_with_open_operation_refused(repo, anchor):
    from asset_based_agent.technical_platform.agent_core.errors import (
        OperationBusy,
    )
    repo.create_lane('s1', 'side', name='side', anchor_entry_id=anchor.id)
    repo.begin_operation('s1', 'side', user_text='进行中', request_id='r2')
    with pytest.raises(OperationBusy):
        repo.delete_lane('s1', 'side')


def test_delete_lane_with_child_lane_refused(repo, anchor):
    repo.create_lane('s1', 'side', name='side', anchor_entry_id=anchor.id)
    repo.create_lane('s1', 'grand', name='grand', parent_lane_id='side',
                     anchor_entry_id=anchor.id)
    with pytest.raises(ValueError, match='子分支'):
        repo.delete_lane('s1', 'side')


def test_create_lane_with_unknown_anchor_refused(repo, anchor):
    with pytest.raises(KeyError):
        repo.create_lane('s1', 'side', name='side',
                         anchor_entry_id='no-such-entry')


# ------------------------------------------------------------------ 只读会话

def test_readonly_session_rejects_new_operations(repo):
    repo.create_session('s1', project_id='p1', owner_id='alice',
                        title='只读历史', permission_mode='readonly')
    with pytest.raises(ValueError, match='只读'):
        repo.begin_operation('s1', 'main', user_text='一', request_id='r1')
    assert repo.entries('s1', 'main') == []


# ------------------------------------------------------------------ 读取不产生写入（SQLite 专属）

def test_tree_reads_do_not_write(tmp_path):
    import sqlite3

    repo = _sqlite_repo(tmp_path)
    repo.create_session('s1', project_id='p1', owner_id='alice', title='会话')
    operation = repo.begin_operation('s1', 'main', user_text='一', request_id='r1')
    reply = repo.append_entry('s1', 'main', 'assistant_message', {'text': '答'})
    repo.complete_operation(operation.id, assistant_entry_id=reply.id,
                            turn_id=None)
    repo.create_lane('s1', 'side', name='side', anchor_entry_id=reply.id)

    def counts():
        with sqlite3.connect(repo.path) as db:
            return {table: db.execute(
                f'SELECT COUNT(*) FROM {table}').fetchone()[0]
                for table in ('agent_sessions', 'agent_lanes',
                              'conversation_entries', 'agent_operations',
                              'agent_operation_events')}

    before = counts()
    repo.tree('s1')
    repo.lane_history('s1', 'main')
    repo.lane_history('s1', 'side', limit=5)
    repo.entries('s1', 'main')
    assert counts() == before, '打开和读取树不产生任何写入'
