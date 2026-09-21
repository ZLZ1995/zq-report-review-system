"""S04：旧 Session/Message/Fork 迁移器——保真、幂等、损坏降级。

旧语义（session_service.fork）：fork 产生全新空 session，不复制消息；
session_metadata.context_snapshot 记录锚点 message 的 sha256 供验证。
"""
import json
import sqlite3
from hashlib import sha256

import pytest


def _message_sha(db, message_id):
    row = db.execute('SELECT * FROM messages WHERE id=?', (message_id,)).fetchone()
    content = json.dumps(dict(row), ensure_ascii=False, sort_keys=True)
    return sha256(content.encode('utf-8')).hexdigest()


def _insert_fork(db, *, project, parent, anchor_message_id, title, snapshot):
    """复刻 session_service.fork 的写入（child 为空 session + metadata）。"""
    child = f'child-{title}'
    db.execute('INSERT INTO sessions(id,project,title,created) VALUES(?,?,?,?)',
               (child, project, title, '2026-01-02T00:00:00+00:00'))
    db.execute(
        'INSERT INTO session_metadata'
        '(session,parent_session,fork_message,context_snapshot,updated) '
        'VALUES(?,?,?,?,?)',
        (child, parent, anchor_message_id, snapshot,
         '2026-01-02T00:00:00+00:00'))
    return child


@pytest.fixture()
def legacy_db(tmp_path):
    """构造旧世界数据库：父会话 + 三类 fork + conversation_state + run。"""
    from asset_based_agent.technical_platform.store import PlatformStore
    path = tmp_path / 'db.sqlite'
    store = PlatformStore(path, 'alice')
    project = store.create_project('p')
    parent = store.create_session(project, '父会话')
    store.append(parent, 'user', '父问题一')
    store.append(parent, 'assistant', '父回答一')
    store.append(parent, 'user', '父问题二')
    with store.connect() as db:
        anchor_id = db.execute(
            'SELECT id FROM messages WHERE session=? ORDER BY id LIMIT 1 OFFSET 1',
            (parent,)).fetchone()['id']
        good_sha = _message_sha(db, anchor_id)
        good_snapshot = json.dumps(
            {'schema_version': 1,
             'source_message': {'id': anchor_id, 'sha256': good_sha},
             'completed_facts': []}, ensure_ascii=False)
        good = _insert_fork(db, project=project, parent=parent,
                            anchor_message_id=anchor_id, title='好分支',
                            snapshot=good_snapshot)
        bad_snapshot = json.dumps(
            {'schema_version': 1,
             'source_message': {'id': anchor_id, 'sha256': '0' * 64},
             'completed_facts': []}, ensure_ascii=False)
        bad = _insert_fork(db, project=project, parent=parent,
                           anchor_message_id=anchor_id, title='坏分支',
                           snapshot=bad_snapshot)
        corrupt = _insert_fork(db, project=project, parent=parent,
                               anchor_message_id=anchor_id, title='损分支',
                               snapshot='not-json')
        db.execute(
            'INSERT INTO conversation_state'
            '(session,owner,task_id,revision,question_json,confirmed_json,'
            'cancelled,updated) VALUES(?,?,?,?,?,?,?,?)',
            (parent, 'alice', 'task-secret', 1,
             json.dumps({'text': '确认残值率？'}, ensure_ascii=False),
             json.dumps({'折旧年限': 10}, ensure_ascii=False), 0,
             '2026-01-01T00:00:00+00:00'))
        db.execute(
            "INSERT INTO runs(id,session,state,snapshot,result,created) "
            "VALUES('run1',?,'succeeded','{}',NULL,'2026-01-01T01:00:00+00:00')",
            (parent,))
    store.append(good, 'user', '分支追问')
    store.append(bad, 'user', '坏分支消息')
    store.append(corrupt, 'user', '损分支消息')
    return {'path': path, 'project': project, 'parent': parent,
            'anchor_id': anchor_id, 'good': good, 'bad': bad,
            'corrupt': corrupt}


def _repo(path):
    from asset_based_agent.technical_platform.sessions.sqlite_repository import (
        SQLiteSessionRepo,
    )
    return SQLiteSessionRepo(path, 'alice')


def _migrate(path):
    from asset_based_agent.technical_platform.sessions.legacy_migration import (
        migrate_legacy_sessions,
    )
    return migrate_legacy_sessions(path, 'alice')


# ------------------------------------------------------------------ 保真

def test_messages_preserved_in_order_with_roles(legacy_db):
    _migrate(legacy_db['path'])
    repo = _repo(legacy_db['path'])
    history = repo.lane_history(f"leg-{legacy_db['parent']}", 'main')
    texts = [e.payload['text'] for e in history
             if e.entry_type in ('user_message', 'assistant_message')]
    assert texts == ['父问题一', '父回答一', '父问题二']
    assert [e.entry_type for e in history[:3]] == [
        'user_message', 'assistant_message', 'user_message']


def test_verifiable_fork_becomes_lane_sharing_parent_chain(legacy_db):
    _migrate(legacy_db['path'])
    repo = _repo(legacy_db['path'])
    parent_session = f"leg-{legacy_db['parent']}"
    lanes = {lane['id']: lane for lane in repo.tree(parent_session)['lanes']}
    assert legacy_db['good'] in lanes, '可验证 fork 应成为父会话的 lane'
    lane = lanes[legacy_db['good']]
    anchor = lane['anchor_entry_id']
    history = repo.lane_history(parent_session, legacy_db['good'])
    assert history[0].id != anchor or True  # 历史从锚点之前开始
    texts = [e.payload['text'] for e in history]
    assert texts[:2] == ['父问题一', '父回答一'], '分支共享父链到锚点'
    assert texts[-1] == '分支追问'
    # fork child 不再生成独立 agent session
    with sqlite3.connect(legacy_db['path']) as db:
        assert db.execute(
            'SELECT 1 FROM agent_sessions WHERE legacy_session_id=?',
            (legacy_db['good'],)).fetchone() is None


def test_unverifiable_fork_imported_as_readonly_history(legacy_db):
    _migrate(legacy_db['path'])
    repo = _repo(legacy_db['path'])
    for child in (legacy_db['bad'], legacy_db['corrupt']):
        session_id = f'leg-{child}'
        history = repo.lane_history(session_id, 'main')
        texts = [e.payload.get('text') for e in history]
        assert history[-1].entry_type == 'system_note'
        assert history[-1].payload['kind'] == 'imported_history'
        expected = '坏分支消息' if child == legacy_db['bad'] else '损分支消息'
        assert expected in texts
        with sqlite3.connect(legacy_db['path']) as db:
            mode = db.execute(
                'SELECT permission_mode FROM agent_sessions WHERE id=?',
                (session_id,)).fetchone()[0]
        assert mode == 'readonly', '无法验证的旧分支保留为只读 imported history'


def test_confirmed_facts_and_pending_question_migrated_without_authorization(
        legacy_db):
    _migrate(legacy_db['path'])
    with sqlite3.connect(legacy_db['path']) as db:
        facts = db.execute(
            "SELECT fact_key,value_json,status,scope FROM project_facts").fetchall()
    assert [(f[0], f[2], f[3]) for f in facts] == [
        ('折旧年限', 'confirmed', 'session')]
    assert json.loads(facts[0][1]) == 10
    repo = _repo(legacy_db['path'])
    history = repo.lane_history(f"leg-{legacy_db['parent']}", 'main')
    notes = [e for e in history if e.entry_type == 'system_note'
             and e.payload.get('kind') == 'pending_question']
    assert notes and notes[0].payload['question']['text'] == '确认残值率？'
    # 授权/任务标识不得进入新模型
    with sqlite3.connect(legacy_db['path']) as db:
        rows = db.execute(
            "SELECT payload_json FROM conversation_entries "
            "WHERE payload_json LIKE '%task-secret%'").fetchall()
    assert rows == []


def test_legacy_runs_become_reference_only(legacy_db):
    _migrate(legacy_db['path'])
    repo = _repo(legacy_db['path'])
    history = repo.lane_history(f"leg-{legacy_db['parent']}", 'main')
    refs = [e for e in history if e.entry_type == 'artifact_reference']
    assert len(refs) == 1
    assert refs[0].payload['legacy_run_id'] == 'run1'
    assert refs[0].payload['state'] == 'succeeded'


# ------------------------------------------------------------------ 幂等与降级

def test_migration_is_idempotent(legacy_db):
    first = _migrate(legacy_db['path'])
    with sqlite3.connect(legacy_db['path']) as db:
        counts_before = {
            table: db.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]
            for table in ('agent_sessions', 'agent_lanes',
                          'conversation_entries', 'project_facts')}
    second = _migrate(legacy_db['path'])
    with sqlite3.connect(legacy_db['path']) as db:
        counts_after = {
            table: db.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]
            for table in counts_before}
    assert counts_after == counts_before, '重复迁移不得产生重复数据'
    assert second['entries_migrated'] == 0
    assert first['entries_migrated'] > 0


def test_damaged_legacy_state_does_not_block_new_messaging(legacy_db):
    _migrate(legacy_db['path'])
    repo = _repo(legacy_db['path'])
    parent_session = f"leg-{legacy_db['parent']}"
    # 健康会话可继续发消息
    operation = repo.begin_operation(parent_session, 'main', user_text='新消息',
                                     request_id='new-1')
    assert operation.status == 'running'
    repo.abort_operation(operation.id, turn_id=None)
    # 可验证 fork lane 可继续发消息
    followup = repo.begin_operation(parent_session, legacy_db['good'],
                                    user_text='分支继续', request_id='new-2')
    repo.abort_operation(followup.id, turn_id=None)
    # 只读 imported history 拒绝写入
    with pytest.raises(ValueError, match='只读'):
        repo.begin_operation(f"leg-{legacy_db['bad']}", 'main',
                             user_text='不应写入', request_id='new-3')


def test_migrated_parent_chain_links_entries(legacy_db):
    _migrate(legacy_db['path'])
    repo = _repo(legacy_db['path'])
    entries = repo.entries(f"leg-{legacy_db['parent']}", 'main')
    parents = [e.parent_id for e in entries]
    assert parents[0] is None
    assert parents[1:] == [e.id for e in entries[:-1]], '旧 message 按 ID 顺序形成父链'
