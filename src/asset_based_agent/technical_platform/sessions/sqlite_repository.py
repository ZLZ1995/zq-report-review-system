"""SQLite SessionRepo：durable Agent Session 真源。

关键事务规则：
- begin_operation：一个 BEGIN IMMEDIATE 事务内完成 lane 校验、开放 operation
  检查、user entry、operation、lane leaf 移动和 operation_accepted 事件；
  部分唯一索引 one_open_operation_per_lane 兜底跨进程竞态。
- 任何状态转换与对应 entry/event 在同一事务提交。
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

from ..agent_core.contracts import ModelRequest
from ..agent_core.errors import OperationBusy
from ..agent_core.messages import SCHEMA_VERSION as ENTRY_SCHEMA_VERSION
from ..agent_core.messages import ConversationEntry
from .models import (
    BINDING_KINDS,
    EXPLICIT_BINDING_KINDS,
    FACT_STATUS_TRANSITIONS,
    OPEN_STATUSES,
    OPERATION_KINDS,
    SESSION_SCHEMA_VERSION,
    Operation,
    ToolCall,
    Turn,
)

_EMPTY_SHA = sha256(b'{}').hexdigest()


def _now():
    return datetime.now(timezone.utc).isoformat()


class SQLiteSessionRepo:
    def __init__(self, path, owner):
        self.path = Path(path)
        self.owner = owner

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path.resolve().as_uri() + '?mode=rw',
                             uri=True, timeout=15)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        try:
            with db:
                yield db
        finally:
            db.close()

    # ------------------------------------------------------------ helpers

    def _lane(self, db, session_id, lane_id):
        row = db.execute(
            'SELECT l.*, s.permission_mode AS session_permission_mode '
            'FROM agent_lanes l JOIN agent_sessions s ON s.id=l.session_id '
            'WHERE l.id=? AND l.session_id=? AND s.owner_id=?',
            (lane_id, session_id, self.owner)).fetchone()
        if row is None:
            raise KeyError(f'未知 lane: {session_id}/{lane_id}')
        return row

    def _insert_entry(self, db, session_id, lane_id, entry_type, payload, *,
                      operation_id, turn_id, leaf_entry_id):
        sequence = db.execute(
            'SELECT COALESCE(MAX(sequence),0)+1 FROM conversation_entries WHERE session_id=?',
            (session_id,)).fetchone()[0]
        entry_id = uuid4().hex
        created = _now()
        db.execute(
            'INSERT INTO conversation_entries '
            '(id,session_id,lane_id,parent_id,sequence,entry_type,payload_json,'
            'operation_id,turn_id,schema_version,created_at) '
            'VALUES(?,?,?,?,?,?,?,?,?,?,?)',
            (entry_id, session_id, lane_id, leaf_entry_id, sequence, entry_type,
             json.dumps(payload, ensure_ascii=False), operation_id, turn_id,
             ENTRY_SCHEMA_VERSION, created))
        db.execute('UPDATE agent_lanes SET leaf_entry_id=?, updated_at=? WHERE id=?',
                   (entry_id, created, lane_id))
        return ConversationEntry(
            id=entry_id, session_id=session_id, lane_id=lane_id,
            parent_id=leaf_entry_id, sequence=sequence, entry_type=entry_type,
            payload=dict(payload), operation_id=operation_id, turn_id=turn_id,
            schema_version=ENTRY_SCHEMA_VERSION, created_at=created)

    def _insert_event(self, db, session_id, lane_id, event_type, *,
                      operation_id=None, turn_id=None, tool_call_id=None,
                      payload=None):
        db.execute(
            'INSERT INTO agent_operation_events '
            '(session_id,lane_id,operation_id,turn_id,tool_call_id,'
            'event_type,payload_json,created_at) '
            'VALUES(?,?,?,?,?,?,?,?)',
            (session_id, lane_id, operation_id, turn_id, tool_call_id,
             event_type, json.dumps(payload or {}, ensure_ascii=False),
             _now()))

    # ---------------------------------------------------------- structure

    def create_session(self, session_id, *, project_id, owner_id, title,
                       permission_mode='full'):
        now = _now()
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute(
                'INSERT INTO agent_sessions '
                '(id,project_id,owner_id,title,schema_version,status,default_lane_id,'
                'permission_mode,revision,created_at,updated_at,last_activity_at) '
                'VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
                (session_id, project_id, owner_id, title, SESSION_SCHEMA_VERSION,
                 'active', 'main', permission_mode, 1, now, now, now))
            db.execute(
                'INSERT INTO agent_lanes '
                '(id,session_id,name,state,revision,created_at,updated_at) '
                "VALUES(?,?,?,'idle',1,?,?)",
                ('main', session_id, 'main', now, now))

    def create_lane(self, session_id, lane_id, *, name, parent_lane_id=None,
                    anchor_entry_id=None):
        now = _now()
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if db.execute(
                'SELECT 1 FROM agent_sessions WHERE id=? AND owner_id=?',
                (session_id, self.owner)).fetchone() is None:
                raise KeyError(f'未知会话: {session_id}')
            if parent_lane_id is not None:
                self._lane(db, session_id, parent_lane_id)
            if anchor_entry_id is not None and db.execute(
                'SELECT 1 FROM conversation_entries WHERE id=? AND session_id=?',
                (anchor_entry_id, session_id)).fetchone() is None:
                raise KeyError(f'未知锚点 entry: {anchor_entry_id}')
            db.execute(
                'INSERT INTO agent_lanes '
                '(id,session_id,name,parent_lane_id,anchor_entry_id,leaf_entry_id,'
                'state,revision,created_at,updated_at) VALUES(?,?,?,?,?,?,?,1,?,?)',
                (lane_id, session_id, name, parent_lane_id, anchor_entry_id,
                 anchor_entry_id, 'idle', now, now))

    # ------------------------------------------------------------- entries

    def append_entry(self, session_id, lane_id, entry_type, payload, *,
                     operation_id=None, turn_id=None):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            lane = self._lane(db, session_id, lane_id)
            return self._insert_entry(
                db, session_id, lane_id, entry_type, payload,
                operation_id=operation_id, turn_id=turn_id,
                leaf_entry_id=lane['leaf_entry_id'])

    def entries(self, session_id, lane_id):
        with self.connect() as db:
            rows = db.execute(
                'SELECT * FROM conversation_entries WHERE session_id=? AND lane_id=? '
                'ORDER BY sequence', (session_id, lane_id)).fetchall()
        return [ConversationEntry(
            id=row['id'], session_id=row['session_id'], lane_id=row['lane_id'],
            parent_id=row['parent_id'], sequence=row['sequence'],
            entry_type=row['entry_type'],
            payload=json.loads(row['payload_json']),
            operation_id=row['operation_id'], turn_id=row['turn_id'],
            schema_version=row['schema_version'], created_at=row['created_at'])
            for row in rows]

    # --------------------------------------------------------------- tree

    def lane_history(self, session_id, lane_id, *, limit=None):
        """沿父链从 leaf 回溯（可跨 lane），按时间顺序返回，最多 limit 条。"""
        cap = 10000 if limit is None else limit
        with self.connect() as db:
            lane = self._lane(db, session_id, lane_id)
            leaf = lane['leaf_entry_id']
            if leaf is None:
                return []
            rows = db.execute(
                'WITH RECURSIVE chain(id, parent_id, depth) AS ('
                'SELECT id, parent_id, 0 FROM conversation_entries '
                'WHERE id=? AND session_id=? '
                'UNION ALL '
                'SELECT e.id, e.parent_id, c.depth+1 '
                'FROM conversation_entries e JOIN chain c ON e.id=c.parent_id '
                'WHERE c.depth < ?) '
                'SELECT e.* FROM conversation_entries e '
                'JOIN chain c ON e.id=c.id ORDER BY c.depth DESC',
                (leaf, session_id, cap - 1)).fetchall()
        return [ConversationEntry(
            id=row['id'], session_id=row['session_id'], lane_id=row['lane_id'],
            parent_id=row['parent_id'], sequence=row['sequence'],
            entry_type=row['entry_type'],
            payload=json.loads(row['payload_json']),
            operation_id=row['operation_id'], turn_id=row['turn_id'],
            schema_version=row['schema_version'], created_at=row['created_at'])
            for row in rows]

    def tree(self, session_id):
        """Tree projection：纯 SELECT，不产生任何写入。"""
        with self.connect() as db:
            if db.execute(
                'SELECT 1 FROM agent_sessions WHERE id=? AND owner_id=?',
                (session_id, self.owner)).fetchone() is None:
                raise KeyError(f'未知会话: {session_id}')
            rows = db.execute(
                'SELECT l.*, (SELECT COUNT(*) FROM conversation_entries e '
                'WHERE e.session_id=l.session_id AND e.lane_id=l.id) '
                'AS entry_count FROM agent_lanes l '
                'WHERE l.session_id=? ORDER BY l.created_at, l.id',
                (session_id,)).fetchall()
        return {'session_id': session_id, 'lanes': [
            {'id': row['id'], 'name': row['name'],
             'parent_lane_id': row['parent_lane_id'],
             'anchor_entry_id': row['anchor_entry_id'],
             'leaf_entry_id': row['leaf_entry_id'], 'state': row['state'],
             'entry_count': row['entry_count']} for row in rows]}

    def delete_lane(self, session_id, lane_id):
        if lane_id == 'main':
            raise ValueError('main lane 不可删除')
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            self._lane(db, session_id, lane_id)
            if db.execute(
                'SELECT 1 FROM agent_operations WHERE lane_id=? AND session_id=? '
                f"AND status IN ({','.join('?' * len(OPEN_STATUSES))}) LIMIT 1",
                (lane_id, session_id, *sorted(OPEN_STATUSES))).fetchone():
                raise OperationBusy('本会话分支正在处理上一条消息')
            if db.execute(
                'SELECT 1 FROM agent_operations WHERE session_id=? AND lane_id=? '
                'LIMIT 1', (session_id, lane_id)).fetchone():
                raise ValueError('lane 已有操作历史，审计记录不可删除')
            if db.execute(
                'SELECT 1 FROM agent_lanes WHERE session_id=? AND '
                '(parent_lane_id=? OR anchor_entry_id IN '
                '(SELECT id FROM conversation_entries '
                'WHERE session_id=? AND lane_id=?)) LIMIT 1',
                (session_id, lane_id, session_id, lane_id)).fetchone():
                raise ValueError('存在子分支，无法删除')
            db.execute(
                'DELETE FROM conversation_entries WHERE session_id=? AND lane_id=?',
                (session_id, lane_id))
            db.execute(
                'DELETE FROM agent_lanes WHERE session_id=? AND id=?',
                (session_id, lane_id))

    # ---------------------------------------------------------- operations

    def begin_operation(self, session_id, lane_id, *, user_text, request_id,
                        kind='consult'):
        if kind not in OPERATION_KINDS:
            raise ValueError(f'非法 operation 类型: {kind}')
        now = _now()
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            lane = self._lane(db, session_id, lane_id)
            if lane['session_permission_mode'] == 'readonly':
                raise ValueError('只读历史会话禁止写入')
            if db.execute(
                'SELECT 1 FROM agent_operations WHERE lane_id=? AND session_id=? '
                f"AND status IN ({','.join('?' * len(OPEN_STATUSES))}) LIMIT 1",
                (lane_id, session_id, *sorted(OPEN_STATUSES))).fetchone():
                raise OperationBusy('本会话分支正在处理上一条消息')
            source = self._insert_entry(
                db, session_id, lane_id, 'user_message', {'text': user_text},
                operation_id=None, turn_id=None,
                leaf_entry_id=lane['leaf_entry_id'])
            operation_id = uuid4().hex
            try:
                db.execute(
                    'INSERT INTO agent_operations '
                    '(id,session_id,lane_id,kind,status,request_id,source_entry_id,'
                    'accepted_context_sha256,permission_snapshot_json,'
                    'file_scope_snapshot_json,resource_snapshot_json,recovery_policy,'
                    'accepted_at,started_at,schema_version) '
                    'VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                    (operation_id, session_id, lane_id, kind, 'running', request_id,
                     source.id, _EMPTY_SHA, '{}', '{}', '{}', 'manual', now, now,
                     SESSION_SCHEMA_VERSION))
            except sqlite3.IntegrityError as exc:
                if 'one_open_operation_per_lane' in str(exc):
                    raise OperationBusy('本会话分支正在处理上一条消息') from exc
                raise
            self._insert_event(db, session_id, lane_id, 'operation_accepted',
                               operation_id=operation_id,
                               payload={'request_id': request_id})
            return Operation(id=operation_id, session_id=session_id,
                             lane_id=lane_id, request_id=request_id,
                             source_entry_id=source.id, kind=kind,
                             status='running', accepted_at=now, started_at=now)

    def _operation_row(self, db, operation_id):
        row = db.execute(
            'SELECT o.* FROM agent_operations o '
            'JOIN agent_sessions s ON s.id=o.session_id '
            'WHERE o.id=? AND s.owner_id=?', (operation_id, self.owner)).fetchone()
        if row is None:
            raise KeyError(f'未知 operation: {operation_id}')
        return row

    def get_operation(self, operation_id):
        with self.connect() as db:
            row = self._operation_row(db, operation_id)
        return Operation(
            id=row['id'], session_id=row['session_id'], lane_id=row['lane_id'],
            request_id=row['request_id'], source_entry_id=row['source_entry_id'],
            kind=row['kind'], status=row['status'],
            current_turn_id=row['current_turn_id'], error_code=row['error_code'],
            error_summary=row['error_summary'], accepted_at=row['accepted_at'],
            started_at=row['started_at'], finished_at=row['finished_at'],
            recovery_policy=row['recovery_policy'])

    def open_operations(self, session_id=None):
        query = ('SELECT o.id FROM agent_operations o '
                 'JOIN agent_sessions s ON s.id=o.session_id '
                 f"WHERE o.status IN ({','.join('?' * len(OPEN_STATUSES))}) "
                 'AND s.owner_id=?')
        params = [*sorted(OPEN_STATUSES), self.owner]
        if session_id is not None:
            query += ' AND o.session_id=?'
            params.append(session_id)
        with self.connect() as db:
            rows = db.execute(query, params).fetchall()
        return [self.get_operation(row['id']) for row in rows]

    def _finish_operation(self, operation_id, status, *, turn_id, event_type,
                          error_code=None, error_summary=None, error_entry=None):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = self._operation_row(db, operation_id)
            db.execute(
                'UPDATE agent_operations SET status=?, current_turn_id=?, '
                'error_code=?, error_summary=?, finished_at=? WHERE id=?',
                (status, turn_id, error_code, error_summary, _now(), operation_id))
            if error_entry is not None:
                lane = self._lane(db, row['session_id'], row['lane_id'])
                self._insert_entry(
                    db, row['session_id'], row['lane_id'], 'error_message',
                    error_entry, operation_id=operation_id, turn_id=turn_id,
                    leaf_entry_id=lane['leaf_entry_id'])
            self._insert_event(db, row['session_id'], row['lane_id'], event_type,
                               operation_id=operation_id, turn_id=turn_id,
                               payload={'error_code': error_code} if error_code else {})

    def complete_operation(self, operation_id, *, assistant_entry_id, turn_id):
        self._finish_operation(operation_id, 'completed', turn_id=turn_id,
                               event_type='operation_completed')

    def fail_operation(self, operation_id, *, code, summary, turn_id):
        self._finish_operation(
            operation_id, 'failed', turn_id=turn_id,
            event_type='operation_failed', error_code=code, error_summary=summary,
            error_entry={'text': f'本轮处理未完成（{code}）。', 'error_code': code})

    def abort_operation(self, operation_id, *, turn_id):
        self._finish_operation(
            operation_id, 'aborted', turn_id=turn_id,
            event_type='operation_aborted', error_code='agent.cancelled',
            error_entry={'text': '本轮已取消。', 'error_code': 'agent.cancelled'})

    def interrupt_operation(self, operation_id, *, code, summary):
        """崩溃恢复：operation/turn/tool call 全部收束为 unknown。"""
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = self._operation_row(db, operation_id)
            now = _now()
            db.execute(
                "UPDATE agent_turns SET status='unknown', error_code=?, "
                'finished_at=? WHERE operation_id=? AND status IN '
                "('queued','model_streaming','tool_batch',"
                "'awaiting_continuation')",
                (code, now, operation_id))
            db.execute(
                "UPDATE agent_tool_calls SET status='unknown', error_code=?, "
                'finished_at=? WHERE operation_id=? AND status IN '
                "('proposed','running')",
                (code, now, operation_id))
            db.execute(
                "UPDATE agent_operations SET status='unknown', error_code=?, "
                'error_summary=?, finished_at=? WHERE id=?',
                (code, summary, now, operation_id))
            lane = self._lane(db, row['session_id'], row['lane_id'])
            self._insert_entry(
                db, row['session_id'], row['lane_id'], 'error_message',
                {'text': f'本轮被中断（{code}），等待对账。', 'error_code': code},
                operation_id=operation_id, turn_id=None,
                leaf_entry_id=lane['leaf_entry_id'])
            self._insert_event(db, row['session_id'], row['lane_id'],
                               'operation_unknown', operation_id=operation_id,
                               payload={'error_code': code})

    # ------------------------------------------------------- snapshots

    def set_resource_snapshot(self, operation_id, resources):
        payload = json.dumps(list(resources), ensure_ascii=False)
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            self._operation_row(db, operation_id)
            db.execute(
                'UPDATE agent_operations SET resource_snapshot_json=? '
                'WHERE id=?', (payload, operation_id))

    def resource_snapshot(self, operation_id):
        with self.connect() as db:
            row = self._operation_row(db, operation_id)
        try:
            data = json.loads(row['resource_snapshot_json'] or '[]')
        except ValueError:
            return []
        return data if isinstance(data, list) else []

    def resume_operation(self, operation_id):
        """按原资源快照恢复中断的 operation：unknown → running。"""
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = self._operation_row(db, operation_id)
            if row['status'] != 'unknown':
                raise ValueError('只有中断（unknown）的 operation 可以恢复')
            db.execute(
                "UPDATE agent_operations SET status='running', "
                'error_code=NULL, error_summary=NULL, finished_at=NULL '
                'WHERE id=?', (operation_id,))
            self._insert_event(db, row['session_id'], row['lane_id'],
                               'operation_resumed', operation_id=operation_id,
                               payload={})

    # --------------------------------------------------------------- turns

    def begin_turn(self, operation_id, ordinal, *, input_context_sha256,
                   model_request_id=''):
        turn_id = uuid4().hex
        with self.connect() as db:
            self._operation_row(db, operation_id)
            db.execute(
                'INSERT INTO agent_turns '
                '(id,operation_id,ordinal,status,model_request_id,'
                'input_context_sha256,started_at) VALUES(?,?,?,?,?,?,?)',
                (turn_id, operation_id, ordinal, 'model_streaming',
                 model_request_id, input_context_sha256, _now()))
        return turn_id

    def finish_turn(self, turn_id, status, *, assistant_entry_id=None,
                    error_code=None, usage=None):
        with self.connect() as db:
            db.execute(
                'UPDATE agent_turns SET status=?, assistant_entry_id=?, '
                'error_code=?, usage_json=?, finished_at=? WHERE id=?',
                (status, assistant_entry_id, error_code,
                 json.dumps(usage or {}, ensure_ascii=False), _now(),
                 turn_id))

    def turns(self, operation_id):
        with self.connect() as db:
            rows = db.execute(
                'SELECT * FROM agent_turns WHERE operation_id=? '
                'ORDER BY ordinal', (operation_id,)).fetchall()
        return [Turn(
            id=row['id'], operation_id=row['operation_id'],
            ordinal=row['ordinal'], status=row['status'],
            model_request_id=row['model_request_id'],
            input_context_sha256=row['input_context_sha256'],
            assistant_entry_id=row['assistant_entry_id'],
            started_at=row['started_at'], finished_at=row['finished_at'],
            error_code=row['error_code'],
            usage=json.loads(row['usage_json'] or '{}')) for row in rows]

    # ----------------------------------------------------------- tool calls

    def begin_tool_call(self, operation_id, turn_id, *, name, arguments,
                        risk, idempotency_key):
        call_id = uuid4().hex
        canonical = json.dumps(arguments, ensure_ascii=False, sort_keys=True)
        digest = sha256(canonical.encode('utf-8')).hexdigest()
        with self.connect() as db:
            self._operation_row(db, operation_id)
            try:
                db.execute(
                    'INSERT INTO agent_tool_calls '
                    '(id,operation_id,turn_id,tool_name,arguments_json,'
                    'arguments_sha256,risk_level,status,idempotency_key,'
                    'started_at) VALUES(?,?,?,?,?,?,?,?,?,?)',
                    (call_id, operation_id, turn_id, name, canonical, digest,
                     risk, 'proposed', idempotency_key, _now()))
            except sqlite3.IntegrityError as exc:
                if 'idempotency_key' in str(exc) or 'UNIQUE' in str(exc):
                    raise ValueError(
                        f'idempotency_key 重复: {idempotency_key}') from exc
                raise
        return call_id

    def set_tool_call_authorization(self, call_id, authorization_id):
        with self.connect() as db:
            db.execute(
                'UPDATE agent_tool_calls SET authorization_id=? WHERE id=?',
                (authorization_id, call_id))

    def finish_tool_call(self, call_id, status, *, result_entry_id=None,
                         error_code=None):
        with self.connect() as db:
            db.execute(
                'UPDATE agent_tool_calls SET status=?, result_entry_id=?, '
                'error_code=?, finished_at=? WHERE id=?',
                (status, result_entry_id, error_code, _now(), call_id))

    def tool_calls(self, operation_id):
        with self.connect() as db:
            rows = db.execute(
                'SELECT * FROM agent_tool_calls WHERE operation_id=? '
                'ORDER BY started_at, id', (operation_id,)).fetchall()
        return [ToolCall(
            id=row['id'], operation_id=row['operation_id'],
            turn_id=row['turn_id'], tool_name=row['tool_name'],
            arguments=json.loads(row['arguments_json']),
            arguments_sha256=row['arguments_sha256'],
            risk_level=row['risk_level'],
            authorization_id=row['authorization_id'], status=row['status'],
            result_entry_id=row['result_entry_id'],
            idempotency_key=row['idempotency_key'],
            started_at=row['started_at'], finished_at=row['finished_at'],
            error_code=row['error_code']) for row in rows]

    # ------------------------------------------------------- permission mode

    def session_permission_mode(self, session_id):
        with self.connect() as db:
            row = db.execute(
                'SELECT permission_mode FROM agent_sessions WHERE id=? AND owner_id=?',
                (session_id, self.owner)).fetchone()
        if row is None:
            raise KeyError(f'未知会话: {session_id}')
        return row['permission_mode']

    def session_project_id(self, session_id):
        with self.connect() as db:
            row = db.execute(
                'SELECT project_id FROM agent_sessions WHERE id=? AND owner_id=?',
                (session_id, self.owner)).fetchone()
        if row is None:
            raise KeyError(f'未知会话: {session_id}')
        return row['project_id']

    def list_sessions(self):
        with self.connect() as db:
            rows = db.execute(
                'SELECT id, project_id, title, permission_mode FROM agent_sessions '
                'WHERE owner_id=? ORDER BY created_at, rowid',
                (self.owner,)).fetchall()
        return [dict(row) for row in rows]

    # ------------------------------------------------- facts / bindings

    def propose_fact(self, project_id, scope, fact_key, value, *,
                     source_entry_id=None, confidence=1.0):
        from ..agent_core.text_safety import contains_secret
        canonical = json.dumps(value, ensure_ascii=False)
        if contains_secret(canonical) or contains_secret(fact_key):
            raise ValueError('禁止把密码、Token 或密钥写入项目事实')
        fact_id = uuid4().hex
        now = _now()
        with self.connect() as db:
            db.execute(
                'INSERT INTO project_facts '
                '(id,project_id,scope,fact_key,value_json,source_entry_id,'
                'confidence,status,created_at,updated_at) '
                'VALUES(?,?,?,?,?,?,?,?,?,?)',
                (fact_id, project_id, scope, fact_key, canonical,
                 source_entry_id, confidence, 'proposed', now, now))
        return fact_id

    def set_fact_status(self, fact_id, status):
        with self.connect() as db:
            row = db.execute('SELECT status FROM project_facts WHERE id=?',
                             (fact_id,)).fetchone()
            if row is None:
                raise KeyError(f'未知事实: {fact_id}')
            if status not in FACT_STATUS_TRANSITIONS.get(row['status'], frozenset()):
                raise ValueError(f"非法事实状态迁移: {row['status']} → {status}")
            db.execute('UPDATE project_facts SET status=?, updated_at=? WHERE id=?',
                       (status, _now(), fact_id))

    def facts(self, project_id, *, status='confirmed', scope=None):
        sql = 'SELECT * FROM project_facts WHERE project_id=? AND status=?'
        params = [project_id, status]
        if scope is not None:
            sql += ' AND scope=?'
            params.append(scope)
        with self.connect() as db:
            rows = db.execute(sql, params).fetchall()
        return [{'id': row['id'], 'project_id': row['project_id'],
                 'scope': row['scope'], 'fact_key': row['fact_key'],
                 'value': json.loads(row['value_json']),
                 'source_entry_id': row['source_entry_id'],
                 'confidence': row['confidence'], 'status': row['status'],
                 'created_at': row['created_at'],
                 'updated_at': row['updated_at']} for row in rows]

    def bind_file(self, operation_id, file_id, binding_kind, *, sha256,
                  role=None, source_entry_id=None):
        if binding_kind not in BINDING_KINDS:
            raise ValueError(f'非法文件绑定类型: {binding_kind}')
        with self.connect() as db:
            self._operation_row(db, operation_id)
            db.execute(
                'INSERT OR REPLACE INTO turn_file_bindings '
                '(operation_id,file_id,binding_kind,source_entry_id,role,sha256) '
                'VALUES(?,?,?,?,?,?)',
                (operation_id, file_id, binding_kind, source_entry_id, role,
                 sha256))

    def operation_files(self, operation_id, kinds=None):
        wanted = EXPLICIT_BINDING_KINDS if kinds is None else frozenset(kinds)
        placeholders = ','.join('?' for _ in wanted)
        with self.connect() as db:
            rows = db.execute(
                f'SELECT * FROM turn_file_bindings WHERE operation_id=? '
                f'AND binding_kind IN ({placeholders})',
                (operation_id, *sorted(wanted))).fetchall()
        return [dict(row) for row in rows]

    # --------------------------------------------------------- compaction

    def save_compaction(self, session_id, lane_id, *, source_start_entry_id,
                        source_end_entry_id, source_sha256, summary_entry_id):
        compaction_id = uuid4().hex
        with self.connect() as db:
            db.execute(
                'INSERT INTO context_compactions '
                '(id,session_id,lane_id,source_start_entry_id,'
                'source_end_entry_id,source_sha256,summary_entry_id,created_at) '
                'VALUES(?,?,?,?,?,?,?,?)',
                (compaction_id, session_id, lane_id, source_start_entry_id,
                 source_end_entry_id, source_sha256, summary_entry_id, _now()))
        return compaction_id

    def latest_compaction(self, session_id, lane_id):
        with self.connect() as db:
            row = db.execute(
                'SELECT * FROM context_compactions WHERE session_id=? '
                'AND lane_id=? ORDER BY created_at DESC, rowid DESC LIMIT 1',
                (session_id, lane_id)).fetchone()
        return dict(row) if row is not None else None

    def set_permission_mode(self, session_id, mode):
        if mode not in {'request', 'assisted', 'full'}:
            raise ValueError(f'非法权限模式: {mode}')
        with self.connect() as db:
            updated = db.execute(
                'UPDATE agent_sessions SET permission_mode=?, updated_at=? '
                'WHERE id=? AND owner_id=?',
                (mode, _now(), session_id, self.owner))
            if updated.rowcount != 1:
                raise KeyError(f'未知会话: {session_id}')

    # --------------------------------------------------------------- events

    def record_event(self, session_id, lane_id, event_type, *,
                     operation_id=None, turn_id=None, tool_call_id=None,
                     payload=None):
        with self.connect() as db:
            self._insert_event(db, session_id, lane_id, event_type,
                               operation_id=operation_id, turn_id=turn_id,
                               tool_call_id=tool_call_id, payload=payload)

    def persisted_events(self, session_id):
        with self.connect() as db:
            rows = db.execute(
                'SELECT * FROM agent_operation_events WHERE session_id=? '
                'ORDER BY sequence', (session_id,)).fetchall()
        return [{'sequence': row['sequence'], 'session_id': row['session_id'],
                 'lane_id': row['lane_id'], 'operation_id': row['operation_id'],
                 'turn_id': row['turn_id'], 'tool_call_id': row['tool_call_id'],
                 'event_type': row['event_type'],
                 'payload': json.loads(row['payload_json']),
                 'created_at': row['created_at']} for row in rows]

    # -------------------------------------------------------------- model

    def build_model_request(self, operation):
        history = tuple(
            {'role': e.entry_type, 'payload': e.payload}
            for e in self.entries(operation.session_id, operation.lane_id))
        return ModelRequest(model_id='', messages=history,
                            request_id=operation.request_id)

    # ---------------------------------------------------------- integrity

    _FK_TABLES = (
        'conversation_entries', 'agent_operations', 'agent_turns',
        'agent_tool_calls', 'turn_file_bindings',
    )

    def validate_integrity(self):
        """结构完整性校验：quick_check、agent 表外键、孤儿 operation。"""
        with self.connect() as db:
            if db.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
                return False
            for table in self._FK_TABLES:
                if db.execute(f'PRAGMA foreign_key_check({table})').fetchall():
                    return False
            orphan = db.execute(
                'SELECT 1 FROM agent_operations o WHERE NOT EXISTS ('
                'SELECT 1 FROM conversation_entries e '
                'WHERE e.id=o.source_entry_id) LIMIT 1').fetchone()
        return orphan is None
