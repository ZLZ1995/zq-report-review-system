"""S16 P3 数据层：run ↔ message 归属关联（测试先行）。

契约（local_migrations v14 + store.py）：
- append 返回新消息整数 ID（旧调用方忽略返回值保持兼容）；
- link_run_messages 仅允许同 session 关联，relation 限定 exact/legacy_inferred/legacy_unlinked；
- append_and_link 完成消息与 run 关联原子提交；
- 重复关联幂等；冲突绑定（同一 run 换绑）拒绝。
"""
import pytest

from asset_based_agent.technical_platform.store import PlatformStore


def make_store(tmp_path, name='state.sqlite'):
    store = PlatformStore(tmp_path / name, 'tester')
    project = store.create_project('归属项目')
    session = store.create_session(project, '归属会话')
    return store, project, session


def start_finished_run(store, session):
    run = store.start_run(session, {'selected_files': [], 'permissions': {}})
    store.transition(run, 'running', 'start')
    store.transition(run, 'validating', 'check')
    store.transition(run, 'succeeded', 'done')
    return run


def test_append_returns_message_id_and_stays_compatible(tmp_path):
    store, _project, session = make_store(tmp_path)
    first = store.append(session, 'user', '你好')
    second = store.append(session, 'assistant', '你好，请问需要核对哪些资料？')
    assert isinstance(first, int) and isinstance(second, int)
    assert second > first
    rows = store.messages(session)
    assert [row['id'] for row in rows] == [first, second]


def test_link_run_messages_exact_and_query(tmp_path):
    store, _project, session = make_store(tmp_path)
    user_id = store.append(session, 'user', '生成评估明细表')
    run = start_finished_run(store, session)
    assistant_id = store.append(session, 'assistant', '已生成 3 个文件。')
    store.link_run_messages(run, source_message_id=user_id,
                            assistant_message_id=assistant_id)
    links = store.run_links(session)
    assert len(links) == 1
    link = links[0]
    assert link['run_id'] == run
    assert link['session_id'] == session
    assert link['source_message_id'] == user_id
    assert link['assistant_message_id'] == assistant_id
    assert link['relation'] == 'exact'


def test_cross_session_link_rejected(tmp_path):
    store, project, session = make_store(tmp_path)
    other = store.create_session(project, '另一个会话')
    foreign_message = store.append(other, 'assistant', '别的会话的回复')
    run = start_finished_run(store, session)
    with pytest.raises(ValueError, match='会话'):
        store.link_run_messages(run, assistant_message_id=foreign_message)
    assert store.run_links(session) == []


def test_invalid_relation_and_missing_message_rejected(tmp_path):
    store, _project, session = make_store(tmp_path)
    run = start_finished_run(store, session)
    with pytest.raises(ValueError, match='relation'):
        store.link_run_messages(run, relation='guessed')
    with pytest.raises(ValueError, match='消息'):
        store.link_run_messages(run, assistant_message_id=999999)
    assert store.run_links(session) == []


def test_append_and_link_is_atomic(tmp_path):
    store, _project, session = make_store(tmp_path)
    user_id = store.append(session, 'user', '生成评估明细表')
    run = start_finished_run(store, session)
    assistant_id = store.append_and_link(session, 'assistant', '已生成。',
                                         run, source_message_id=user_id)
    link = store.run_links(session)[0]
    assert link['assistant_message_id'] == assistant_id
    assert link['source_message_id'] == user_id
    # 原子性：run 不存在时消息不得落库
    before = len(store.messages(session))
    with pytest.raises((ValueError, PermissionError)):
        store.append_and_link(session, 'assistant', '悬空回复',
                              'no-such-run', source_message_id=user_id)
    assert len(store.messages(session)) == before


def test_duplicate_link_idempotent_and_conflict_rejected(tmp_path):
    store, _project, session = make_store(tmp_path)
    run = start_finished_run(store, session)
    assistant_id = store.append(session, 'assistant', '已生成。')
    store.link_run_messages(run, assistant_message_id=assistant_id)
    store.link_run_messages(run, assistant_message_id=assistant_id)  # 幂等
    assert len(store.run_links(session)) == 1
    other_id = store.append(session, 'assistant', '另一条回复。')
    with pytest.raises(ValueError, match='已关联'):
        store.link_run_messages(run, assistant_message_id=other_id)
    assert store.run_links(session)[0]['assistant_message_id'] == assistant_id
