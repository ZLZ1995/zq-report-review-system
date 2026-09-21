"""S04：旧 Session/Message/Fork → Agent Session/Lane 迁移器（幂等）。

映射规则（计划书 S04 迁移规则）：
- 每个顶层旧 Session → 新 Agent Session（id 形如 leg-<旧id>）的 main lane；
- 旧 message 按 id 顺序形成父链（entry id 确定性：leg-<旧session>-<旧message id>）；
- 可验证 fork（parent 存在、锚点 message 存在、context_snapshot 中 sha256 与
  原 message 重算一致）→ 父 Agent Session 内的新 lane，锚定父链，不复制 Entry；
- 无法验证的 fork（含 snapshot 损坏、sha 不符、祖先不可验证）→ 独立只读
  Agent Session（permission_mode='readonly'）+ imported_history 标记；
- conversation_state 只转换 confirmed facts（→ project_facts）和 pending
  question（→ system_note），task_id/授权一律不转换；
- 旧 Run 只建立 artifact_reference，不复制成果文件；
- 幂等：legacy_session_id 已存在则整棵子树跳过；entry id 确定性兜底。
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from hashlib import sha256

from ..agent_core.messages import SCHEMA_VERSION as ENTRY_SCHEMA_VERSION
from .models import SESSION_SCHEMA_VERSION

ROLE_MAP = {'user': 'user_message', 'assistant': 'assistant_message'}


def _message_sha(row):
    content = json.dumps(dict(row), ensure_ascii=False, sort_keys=True)
    return sha256(content.encode('utf-8')).hexdigest()


class _TreeBuilder:
    """单个 Agent Session 内的 entry 写入器：维护 sequence 与 lane leaf。"""

    def __init__(self, db, session_id):
        self.db = db
        self.session_id = session_id
        self.sequence = 0
        self.count = 0

    def _lane(self, lane_id):
        return self.db.execute(
            'SELECT * FROM agent_lanes WHERE session_id=? AND id=?',
            (self.session_id, lane_id)).fetchone()

    def add_lane(self, lane_id, name, *, parent_lane_id=None,
                 anchor_entry_id=None, created):
        self.db.execute(
            'INSERT INTO agent_lanes '
            '(id,session_id,name,parent_lane_id,anchor_entry_id,leaf_entry_id,'
            'state,revision,created_at,updated_at) VALUES(?,?,?,?,?,?,?,1,?,?)',
            (lane_id, self.session_id, name, parent_lane_id, anchor_entry_id,
             anchor_entry_id, 'idle', created, created))

    def add_entry(self, entry_id, lane_id, entry_type, payload, created):
        lane = self._lane(lane_id)
        self.sequence += 1
        self.db.execute(
            'INSERT INTO conversation_entries '
            '(id,session_id,lane_id,parent_id,sequence,entry_type,payload_json,'
            'operation_id,turn_id,schema_version,created_at) '
            'VALUES(?,?,?,?,?,?,?,NULL,NULL,?,?)',
            (entry_id, self.session_id, lane_id, lane['leaf_entry_id'],
             self.sequence, entry_type,
             json.dumps(payload, ensure_ascii=False),
             ENTRY_SCHEMA_VERSION, created))
        self.db.execute(
            'UPDATE agent_lanes SET leaf_entry_id=?, updated_at=? '
            'WHERE session_id=? AND id=?',
            (entry_id, created, self.session_id, lane_id))
        self.count += 1

    def import_session_contents(self, legacy_session_id, lane_id, *,
                                messages, question, runs, readonly_reason=None):
        for message in messages:
            entry_id = f'leg-{legacy_session_id}-{message["id"]}'
            self.add_entry(
                entry_id, lane_id,
                ROLE_MAP.get(message['role'], 'system_note'),
                {'text': message['text'], 'legacy_message_id': message['id']},
                message['created'])
        if question is not None:
            self.add_entry(
                f'leg-{legacy_session_id}-pending-question', lane_id,
                'system_note',
                {'kind': 'pending_question', 'question': question},
                messages[-1]['created'] if messages else _now(self.db))
        for run in runs:
            self.add_entry(
                f'leg-{legacy_session_id}-run-{run["id"]}', lane_id,
                'artifact_reference',
                {'kind': 'legacy_run_reference', 'legacy_run_id': run['id'],
                 'state': run['state']},
                run['created'])
        if readonly_reason is not None:
            self.add_entry(
                f'leg-{legacy_session_id}-imported-marker', lane_id,
                'system_note',
                {'kind': 'imported_history', 'reason': readonly_reason},
                messages[-1]['created'] if messages else _now(self.db))


def _now(db):
    row = db.execute("SELECT datetime('now')").fetchone()
    return row[0].replace(' ', 'T') + '+00:00'


def _fork_verification(db, metadata, parent_messages_by_id):
    """返回 None（可验证）或拒绝原因字符串。"""
    if metadata is None or not metadata['parent_session']:
        return '缺少 fork 元数据'
    try:
        snapshot = json.loads(metadata['context_snapshot'] or '')
    except (TypeError, ValueError):
        return 'context_snapshot 损坏'
    source = snapshot.get('source_message') or {}
    anchor_id = metadata['fork_message']
    anchor = parent_messages_by_id.get(anchor_id)
    if anchor is None:
        return 'fork 锚点消息不存在'
    if source.get('id') != anchor_id:
        return 'snapshot 锚点 id 不一致'
    if source.get('sha256') != _message_sha(anchor):
        return '锚点消息 sha256 校验失败'
    return None


def migrate_legacy_sessions(path, owner):
    """把旧 sessions/messages/fork 迁移到 v13 agent 模型；返回迁移报告。"""
    report = {'sessions_migrated': 0, 'lanes_migrated': 0,
              'entries_migrated': 0, 'facts_migrated': 0,
              'skipped_existing': 0, 'unverifiable': [], 'damaged': []}
    with closing(sqlite3.connect(str(path), timeout=15)) as db:
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        db.execute('BEGIN IMMEDIATE')
        try:
            sessions = db.execute(
                'SELECT s.* FROM sessions s JOIN projects p ON p.id=s.project '
                'WHERE p.owner=? ORDER BY s.created, s.id', (owner,)).fetchall()
            metadata = {row['session']: row for row in db.execute(
                'SELECT * FROM session_metadata')}
            known_ids = {row['id'] for row in sessions}
            children = {}
            for row in sessions:
                meta = metadata.get(row['id'])
                parent = meta['parent_session'] if meta else None
                if parent and parent in known_ids:
                    children.setdefault(parent, []).append(row['id'])
            tops = [row for row in sessions
                    if row['id'] not in {c for ids in children.values()
                                         for c in ids}]
            for row in tops:
                db.execute('SAVEPOINT legacy_session')
                try:
                    _migrate_top(db, row, metadata, children, owner, report)
                except Exception as exc:  # noqa: BLE001 - 损坏降级为只读标记
                    db.execute('ROLLBACK TO legacy_session')
                    db.execute('RELEASE legacy_session')
                    _import_damaged(db, row, owner, str(exc), report)
                else:
                    db.execute('RELEASE legacy_session')
            db.commit()
        except BaseException:
            db.rollback()
            raise
    return report


def _already_migrated(db, legacy_session_id):
    return db.execute(
        'SELECT 1 FROM agent_sessions WHERE legacy_session_id=?',
        (legacy_session_id,)).fetchone() is not None


def _session_extras(db, legacy_session_id):
    state = db.execute(
        'SELECT * FROM conversation_state WHERE session=?',
        (legacy_session_id,)).fetchone()
    confirmed = question = None
    if state is not None:
        try:
            confirmed = json.loads(state['confirmed_json'] or '{}')
        except (TypeError, ValueError):
            confirmed = None
        try:
            question = (json.loads(state['question_json'])
                        if state['question_json'] else None)
        except (TypeError, ValueError):
            question = None
    runs = db.execute(
        'SELECT * FROM runs WHERE session=? ORDER BY created, id',
        (legacy_session_id,)).fetchall()
    return confirmed, question, runs


def _migrate_facts(db, legacy_session_id, project_id, confirmed, created):
    count = 0
    for key, value in sorted((confirmed or {}).items()):
        cursor = db.execute(
            'INSERT OR IGNORE INTO project_facts '
            '(id,project_id,scope,fact_key,value_json,source_entry_id,'
            'confidence,status,created_at,updated_at) '
            "VALUES(?,?,?,?,?,NULL,NULL,'confirmed',?,?)",
            (f'leg-fact-{legacy_session_id}-{key}', project_id, 'session',
             key, json.dumps(value, ensure_ascii=False), created, created))
        count += cursor.rowcount
    return count


def _create_agent_session(db, *, legacy_session_id, project_id, owner, title,
                          permission_mode, status, created):
    db.execute(
        'INSERT INTO agent_sessions '
        '(id,project_id,owner_id,title,schema_version,status,default_lane_id,'
        'permission_mode,revision,created_at,updated_at,last_activity_at,'
        'legacy_session_id) VALUES(?,?,?,?,?,?,?,?,1,?,?,?,?)',
        (f'leg-{legacy_session_id}', project_id, owner, title,
         SESSION_SCHEMA_VERSION, status, 'main', permission_mode,
         created, created, created, legacy_session_id))


def _migrate_top(db, row, metadata, children, owner, report):
    legacy_id = row['id']
    if _already_migrated(db, legacy_id):
        report['skipped_existing'] += 1
        return
    _create_agent_session(
        db, legacy_session_id=legacy_id, project_id=row['project'],
        owner=owner, title=row['title'], permission_mode='full',
        status='active', created=row['created'])
    session_id = f'leg-{legacy_id}'
    builder = _TreeBuilder(db, session_id)
    builder.add_lane('main', 'main', created=row['created'])
    _migrate_contents(db, builder, row, report)
    _migrate_fork_lanes(db, builder, row, metadata, children, owner, report,
                        host_lane='main')
    report['sessions_migrated'] += 1


def _migrate_contents(db, builder, legacy_row, report):
    legacy_id = legacy_row['id']
    messages = db.execute(
        'SELECT * FROM messages WHERE session=? ORDER BY id',
        (legacy_id,)).fetchall()
    confirmed, question, runs = _session_extras(db, legacy_id)
    before = builder.count
    builder.import_session_contents(
        legacy_id, _lane_of(builder, legacy_id), messages=messages,
        question=question, runs=runs)
    report['entries_migrated'] += builder.count - before
    report['facts_migrated'] += _migrate_facts(
        db, legacy_id, legacy_row['project'], confirmed, legacy_row['created'])


def _lane_of(builder, legacy_id):
    """顶层会话内容落在 main；fork 会话内容落在以旧 id 命名的 lane。"""
    row = builder.db.execute(
        'SELECT 1 FROM agent_lanes WHERE session_id=? AND id=?',
        (builder.session_id, legacy_id)).fetchone()
    return legacy_id if row is not None else 'main'


def _migrate_fork_lanes(db, builder, parent_row, metadata, children, owner,
                        report, *, host_lane):
    parent_id = parent_row['id']
    parent_messages = {m['id']: m for m in db.execute(
        'SELECT * FROM messages WHERE session=?', (parent_id,))}
    for child_id in sorted(children.get(parent_id, [])):
        child = db.execute('SELECT * FROM sessions WHERE id=?',
                           (child_id,)).fetchone()
        meta = metadata.get(child_id)
        reason = _fork_verification(db, meta, parent_messages)
        if reason is None:
            anchor_entry_id = f'leg-{parent_id}-{meta["fork_message"]}'
            builder.add_lane(child_id, child['title'],
                             parent_lane_id=host_lane,
                             anchor_entry_id=anchor_entry_id,
                             created=child['created'])
            report['lanes_migrated'] += 1
            _migrate_contents(db, builder, child, report)
            _migrate_fork_lanes(db, builder, child, metadata, children, owner,
                                report, host_lane=child_id)
        else:
            _import_unverifiable(db, child, metadata, children, owner, reason,
                                 report)


def _import_unverifiable(db, row, metadata, children, owner, reason, report):
    legacy_id = row['id']
    if _already_migrated(db, legacy_id):
        report['skipped_existing'] += 1
        return
    _create_agent_session(
        db, legacy_session_id=legacy_id, project_id=row['project'],
        owner=owner, title=row['title'], permission_mode='readonly',
        status='active', created=row['created'])
    session_id = f'leg-{legacy_id}'
    builder = _TreeBuilder(db, session_id)
    builder.add_lane('main', 'main', created=row['created'])
    messages = db.execute(
        'SELECT * FROM messages WHERE session=? ORDER BY id',
        (legacy_id,)).fetchall()
    confirmed, question, runs = _session_extras(db, legacy_id)
    builder.import_session_contents(
        legacy_id, 'main', messages=messages, question=question, runs=runs,
        readonly_reason=reason)
    report['entries_migrated'] += builder.count
    report['facts_migrated'] += _migrate_facts(
        db, legacy_id, row['project'], confirmed, row['created'])
    report['unverifiable'].append(legacy_id)
    report['sessions_migrated'] += 1
    # 不可验证分支的后代同样降级为独立只读历史
    for child_id in sorted(children.get(legacy_id, [])):
        child = db.execute('SELECT * FROM sessions WHERE id=?',
                           (child_id,)).fetchone()
        _import_unverifiable(db, child, metadata, children, owner,
                             '祖先分支不可验证', report)


def _import_damaged(db, row, owner, error, report):
    legacy_id = row['id']
    if _already_migrated(db, legacy_id):
        return
    _create_agent_session(
        db, legacy_session_id=legacy_id, project_id=row['project'],
        owner=owner, title=row['title'], permission_mode='readonly',
        status='damaged', created=row['created'])
    session_id = f'leg-{legacy_id}'
    builder = _TreeBuilder(db, session_id)
    builder.add_lane('main', 'main', created=row['created'])
    builder.add_entry(f'leg-{legacy_id}-damaged-marker', 'main', 'system_note',
                      {'kind': 'imported_history',
                       'reason': f'旧数据损坏，按只读历史导入: {error}'},
                      row['created'])
    report['entries_migrated'] += builder.count
    report['damaged'].append(legacy_id)
    report['sessions_migrated'] += 1
