"""Local project state. All lookups are scoped to the authenticated owner."""

from __future__ import annotations

import json
import shutil
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


class PlatformStore:
    def __init__(self, path: Path, owner: str, *, create: bool = True) -> None:
        if not owner.strip():
            raise ValueError("owner is required")
        from .local_migrations import (
            SCHEMA_VERSION,
            apply_v1,
            apply_v2,
            apply_v3,
            apply_v4,
            apply_v5,
            apply_v6,
            apply_v7,
            apply_v8,
            apply_v9,
            apply_v10,
            apply_v11,
            apply_v12,
            apply_v13,
            apply_v14,
            migrate_database,
        )

        existing = path.is_file()
        if existing:
            # Reject future schemas and back up legacy state before any CREATE.
            migrate_database(path)
        self.existing_only = not create
        if create:
            path.parent.mkdir(parents=True, exist_ok=True)
        elif not path.is_file():
            raise OSError("项目数据库不存在，不会自动创建替代数据库")
        self.path, self.owner = path, owner
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS projects (
                  id TEXT PRIMARY KEY, owner TEXT NOT NULL, name TEXT NOT NULL,
                  archived INTEGER NOT NULL DEFAULT 0, created TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS sessions (
                  id TEXT PRIMARY KEY, project TEXT NOT NULL REFERENCES projects(id),
                  title TEXT NOT NULL, created TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS messages (
                  id INTEGER PRIMARY KEY, session TEXT REFERENCES sessions(id),
                  role TEXT NOT NULL, text TEXT NOT NULL, created TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS files (
                  id TEXT PRIMARY KEY, project TEXT REFERENCES projects(id),
                  name TEXT NOT NULL, path TEXT NOT NULL, sha256 TEXT NOT NULL,
                  size INTEGER NOT NULL, created TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS runs (
                  id TEXT PRIMARY KEY, session TEXT REFERENCES sessions(id),
                  state TEXT NOT NULL, snapshot TEXT NOT NULL, result TEXT,
                  created TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS events (
                  id INTEGER PRIMARY KEY, run TEXT REFERENCES runs(id),
                  state TEXT NOT NULL, detail TEXT NOT NULL, created TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS memories (
                  id TEXT PRIMARY KEY, project TEXT REFERENCES projects(id),
                  text TEXT NOT NULL, source TEXT NOT NULL, active INTEGER NOT NULL,
                  created TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS feedback (
                  id TEXT PRIMARY KEY, run TEXT REFERENCES runs(id),
                  kind TEXT NOT NULL, text TEXT NOT NULL, created TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS project_claims (
                  project TEXT PRIMARY KEY REFERENCES projects(id),
                  previous_owner TEXT NOT NULL, new_owner TEXT NOT NULL,
                  created TEXT NOT NULL);
            """)
            if not existing:
                apply_v1(db)
                apply_v2(db)
                apply_v3(db)
                apply_v4(db)
                apply_v5(db)
                apply_v6(db)
                apply_v7(db)
                apply_v8(db)
                apply_v9(db)
                apply_v10(db)
                apply_v11(db)
                apply_v12(db)
                apply_v13(db)
                apply_v14(db)
                db.execute(f'PRAGMA user_version={SCHEMA_VERSION}')
        # Creation is allowed only during explicit initialization. Later requests
        # must fail closed if a disk disappears or the database is moved.
        self.existing_only = True

    @contextmanager
    def connect(self):
        db = (sqlite3.connect(self.path.resolve().as_uri() + "?mode=rw", uri=True, timeout=15)
              if self.existing_only else sqlite3.connect(self.path, timeout=15))
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA temp_store=MEMORY")
        try:
            with db:
                yield db
        finally:
            db.close()

    def project(self, project_id: str) -> dict:
        with self.connect() as db:
            row = db.execute(
                "SELECT * FROM projects WHERE id=? AND owner=?",
                (project_id, self.owner),
            ).fetchone()
        if row is None:
            raise PermissionError("项目不存在或无权访问")
        return dict(row)

    def legacy_projects(self) -> list[dict]:
        if self.owner in {"local-preview", "offline-local"}:
            raise PermissionError("请先登录账号再认领旧项目")
        with self.connect() as db:
            return [dict(r) for r in db.execute(
                "SELECT id,name,archived,created FROM projects WHERE owner='local-preview' ORDER BY created"
            )]

    def claim_legacy_project(self, project_id: str, *, confirmed: bool) -> None:
        if self.owner in {"local-preview", "offline-local"}:
            raise PermissionError("请先登录账号再认领旧项目")
        if not confirmed:
            raise ValueError("认领必须由用户明确确认")
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT owner FROM projects WHERE id=?", (project_id,)).fetchone()
            if row is None or row[0] != "local-preview":
                raise PermissionError("不是可认领的旧共享项目，可能已被其他账号认领")
            active = db.execute(
                "SELECT 1 FROM runs r JOIN sessions s ON s.id=r.session "
                "WHERE s.project=? AND r.state IN ('queued','running','validating') LIMIT 1",
                (project_id,),
            ).fetchone()
            if active:
                raise ValueError("旧项目存在未结束任务，请先处理任务状态")
            db.execute("INSERT INTO project_claims VALUES(?,?,?,?)",
                       (project_id, "local-preview", self.owner, now()))
            db.execute("UPDATE projects SET owner=? WHERE id=?", (self.owner, project_id))
            db.execute("UPDATE memory_records SET owner=? WHERE project=?",
                       (self.owner, project_id))

    def session(self, session_id: str) -> dict:
        with self.connect() as db:
            row = db.execute(
                "SELECT s.* FROM sessions s JOIN projects p ON p.id=s.project "
                "WHERE s.id=? AND p.owner=?",
                (session_id, self.owner),
            ).fetchone()
        if row is None:
            raise PermissionError("会话不存在或无权访问")
        return dict(row)

    def create_project(self, name: str) -> str:
        if not name.strip():
            raise ValueError("项目名称不能为空")
        identity = uuid4().hex
        with self.connect() as db:
            db.execute(
                "INSERT INTO projects VALUES (?,?,?,0,?)",
                (identity, self.owner, name.strip(), now()),
            )
        return identity

    def projects(self) -> list[dict]:
        with self.connect() as db:
            return [
                dict(r)
                for r in db.execute(
                    "SELECT * FROM projects WHERE owner=? AND archived=0 ORDER BY created DESC",
                    (self.owner,),
                )
            ]

    def archive(self, project_id: str) -> None:
        self.project(project_id)
        with self.connect() as db:
            db.execute("UPDATE projects SET archived=1 WHERE id=?", (project_id,))

    def rename_project(self, project_id: str, name: str) -> None:
        self.project(project_id)
        value = name.strip()
        if not value or len(value) > 120:
            raise ValueError('项目名称必须为1至120个字符')
        with self.connect() as db:
            db.execute('UPDATE projects SET name=? WHERE id=? AND owner=?',
                       (value, project_id, self.owner))

    def create_session(self, project_id: str, title: str = "新会话") -> str:
        self.project(project_id)
        identity = uuid4().hex
        with self.connect() as db:
            db.execute(
                "INSERT INTO sessions VALUES (?,?,?,?)",
                (identity, project_id, title, now()),
            )
        return identity

    def sessions(self, project_id: str) -> list[dict]:
        from .session_service import SessionService
        return SessionService(self).list(project_id)

    def append(self, session_id: str, role: str, text: str) -> int:
        self.session(session_id)
        if role not in {"user", "assistant", "event"}:
            raise ValueError("invalid message role")
        with self.connect() as db:
            cursor = db.execute(
                "INSERT INTO messages(session,role,text,created) VALUES(?,?,?,?)",
                (session_id, role, text, now()),
            )
            return int(cursor.lastrowid)

    # ------------------------------------------------------------ run ↔ message 归属（v14）

    def link_run_messages(self, run_id: str, source_message_id=None,
                          assistant_message_id=None, relation: str = 'exact') -> None:
        """建立 run 与同会话消息的归属关联；幂等，冲突换绑拒绝。"""
        if relation not in {'exact', 'legacy_inferred', 'legacy_unlinked'}:
            raise ValueError(f'未知关联类型 relation: {relation}')
        run = self.run(run_id)  # owner 校验；不存在 → PermissionError
        session_id = run['session']
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            for message_id in (source_message_id, assistant_message_id):
                if message_id is None:
                    continue
                row = db.execute('SELECT session FROM messages WHERE id=?',
                                 (message_id,)).fetchone()
                if row is None:
                    raise ValueError(f'消息不存在: {message_id}')
                if row[0] != session_id:
                    raise ValueError('不允许跨会话关联 run 与消息')
            existing = db.execute(
                'SELECT source_message_id, assistant_message_id FROM '
                'run_message_links WHERE run_id=?', (run_id,)).fetchone()
            if existing is not None:
                if (existing['source_message_id'], existing['assistant_message_id']) == \
                        (source_message_id, assistant_message_id):
                    return  # 幂等：相同关联重复提交不产生变化
                raise ValueError('该 run 已关联其他消息，禁止换绑')
            db.execute(
                'INSERT INTO run_message_links(run_id, session_id,'
                ' source_message_id, assistant_message_id, relation, created_at)'
                ' VALUES(?,?,?,?,?,?)',
                (run_id, session_id, source_message_id, assistant_message_id,
                 relation, now()))

    def append_and_link(self, session_id: str, role: str, text: str, run_id: str,
                        source_message_id=None) -> int:
        """完成消息与 run 关联原子提交：任何一步失败都不留半截数据。"""
        self.session(session_id)
        if role not in {"user", "assistant", "event"}:
            raise ValueError("invalid message role")
        run = self.run(run_id)
        if run['session'] != session_id:
            raise PermissionError('任务归属与当前会话不一致')
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if source_message_id is not None:
                row = db.execute('SELECT session FROM messages WHERE id=?',
                                 (source_message_id,)).fetchone()
                if row is None:
                    raise ValueError(f'消息不存在: {source_message_id}')
                if row[0] != session_id:
                    raise ValueError('不允许跨会话关联 run 与消息')
            cursor = db.execute(
                "INSERT INTO messages(session,role,text,created) VALUES(?,?,?,?)",
                (session_id, role, text, now()))
            message_id = int(cursor.lastrowid)
            existing = db.execute(
                'SELECT assistant_message_id FROM run_message_links WHERE run_id=?',
                (run_id,)).fetchone()
            if existing is None:
                db.execute(
                    'INSERT INTO run_message_links(run_id, session_id,'
                    ' source_message_id, assistant_message_id, relation, created_at)'
                    " VALUES(?,?,?,?,'exact',?)",
                    (run_id, session_id, source_message_id, message_id, now()))
            elif existing['assistant_message_id'] != message_id:
                raise ValueError('该 run 已关联其他消息，禁止换绑')
            return message_id

    def run_links(self, session_id: str) -> list[dict]:
        self.session(session_id)
        with self.connect() as db:
            return [
                dict(r)
                for r in db.execute(
                    'SELECT * FROM run_message_links WHERE session_id=?'
                    ' ORDER BY created_at, run_id', (session_id,))
            ]

    def messages(self, session_id: str) -> list[dict]:
        self.session(session_id)
        with self.connect() as db:
            return [
                dict(r)
                for r in db.execute(
                    "SELECT * FROM messages WHERE session=? ORDER BY id", (session_id,)
                )
            ]

    def add_file(self, project_id: str, path: Path, digest: str) -> str:
        self.project(project_id)
        from .skills import digest as file_digest

        identity = uuid4().hex
        destination = (
            self.path.parent / "attachments" / project_id / identity / path.name
        )
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, destination)
        if file_digest(destination) != digest:
            destination.unlink()
            raise OSError("文件复制校验失败，请重新添加")
        with self.connect() as db:
            db.execute(
                "INSERT INTO files VALUES(?,?,?,?,?,?,?)",
                (
                    identity,
                    project_id,
                    path.name,
                    str(destination.resolve()),
                    digest,
                    path.stat().st_size,
                    now(),
                ),
            )
        return identity

    def archived_projects(self):
        with self.connect() as db:
            return [
                dict(r)
                for r in db.execute(
                    "SELECT * FROM projects WHERE owner=? AND archived=1 ORDER BY created DESC",
                    (self.owner,),
                )
            ]

    def restore(self, project_id):
        self.project(project_id)
        with self.connect() as db:
            db.execute("UPDATE projects SET archived=0 WHERE id=?", (project_id,))

    def files(self, project_id: str) -> list[dict]:
        self.project(project_id)
        with self.connect() as db:
            return [
                dict(r)
                for r in db.execute(
                    "SELECT * FROM files WHERE project=? ORDER BY created",
                    (project_id,),
                )
            ]

    def start_run(self, session_id: str, snapshot: dict) -> str:
        session = self.session(session_id)
        identity = uuid4().hex
        if "schema_version" in snapshot:
            if type(snapshot["schema_version"]) is not int or snapshot["schema_version"] not in (1, 2):
                raise ValueError("不支持的任务版本")
            if (snapshot.get("owner") != self.owner
                    or snapshot.get("session_id") != session_id
                    or snapshot.get("project_id") != session["project"]):
                raise PermissionError("任务归属与当前会话不一致")
            identity = snapshot["task_id"]
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            metadata = db.execute('SELECT archived FROM session_metadata WHERE session=?', (session_id,)).fetchone()
            if metadata is not None and metadata['archived']:
                raise ValueError('会话已归档，请先恢复后再执行任务')
            db.execute(
                "INSERT INTO runs VALUES(?,?,?, ?,NULL,?)",
                (
                    identity,
                    session_id,
                    "queued",
                    json.dumps(snapshot, ensure_ascii=False),
                    now(),
                ),
            )
        return identity

    def run(self, run_id: str) -> dict:
        with self.connect() as db:
            row = db.execute(
                "SELECT r.* FROM runs r JOIN sessions s ON s.id=r.session "
                "JOIN projects p ON p.id=s.project WHERE r.id=? AND p.owner=?",
                (run_id, self.owner),
            ).fetchone()
        if row is None:
            raise PermissionError("任务不存在或无权访问")
        return dict(row)

    def runs(self, session_id: str) -> list[dict]:
        self.session(session_id)
        with self.connect() as db:
            return [
                dict(r)
                for r in db.execute(
                    "SELECT * FROM runs WHERE session=? ORDER BY created", (session_id,)
                )
            ]

    def claim_run(self, run_id: str) -> dict:
        """Atomically grant the queued run to exactly one execution attempt."""
        self.transition(run_id, "running", "planning: 已领取任务，开始只读计划校验")
        return self.run(run_id)

    def transition(self, run_id: str, state: str, detail: str) -> None:
        allowed = {
            "queued": {"running", "cancelled", "failed"},
            "running": {"validating", "cancelled", "failed", "waiting_user"},
            "validating": {"succeeded", "failed", "cancelled", "waiting_user"},
            # Clarification resume re-enters running; it never re-bills the model.
            "waiting_user": {"running", "cancelled", "failed"},
        }
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT r.state FROM runs r JOIN sessions s ON s.id=r.session "
                "JOIN projects p ON p.id=s.project WHERE r.id=? AND p.owner=?",
                (run_id, self.owner),
            ).fetchone()
            if row is None:
                raise PermissionError("任务不存在或无权访问")
            current = row[0]
            if state not in allowed.get(current, set()):
                raise ValueError(f"非法状态转换：{current} -> {state}")
            db.execute("UPDATE runs SET state=? WHERE id=?", (state, run_id))
            db.execute(
                "INSERT INTO events(run,state,detail,created) VALUES(?,?,?,?)",
                (run_id, state, detail, now()),
            )

    def set_material_resolution_override(self, run_id: str, override: dict) -> None:
        """Attach the user clarification to a waiting run snapshot.

        The override is validated against the persisted candidate set at
        resume time; here we only guarantee the run is actually waiting
        so a clarification can never redirect a running or finished task.
        """
        if not isinstance(override, dict) or not override:
            raise ValueError('澄清结果无效，请重新提交')
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT r.state, r.snapshot FROM runs r JOIN sessions s ON s.id=r.session "
                "JOIN projects p ON p.id=s.project WHERE r.id=? AND p.owner=?",
                (run_id, self.owner),
            ).fetchone()
            if row is None:
                raise PermissionError("任务不存在或无权访问")
            if row['state'] != 'waiting_user':
                raise ValueError('只有等待补充信息的任务可以接受澄清答复')
            snapshot = json.loads(row['snapshot'])
            snapshot['material_resolution_override'] = override
            db.execute("UPDATE runs SET snapshot=? WHERE id=?",
                       (json.dumps(snapshot, ensure_ascii=False), run_id))
            db.execute("INSERT INTO events(run,state,detail,created) VALUES(?,?,?,?)",
                       (run_id, 'waiting_user', '已记录用户澄清，准备从资料消歧节点恢复', now()))

    def save_result(self, run_id: str, result: dict) -> None:
        self.run(run_id)
        with self.connect() as db:
            db.execute(
                "UPDATE runs SET result=? WHERE id=?",
                (json.dumps(result, ensure_ascii=False), run_id),
            )

    def remember(self, project_id: str, text: str, *, confirmed: bool) -> str:
        from .memory_service import MemoryService
        return MemoryService(self).create(
            scope="project", project_id=project_id, key="legacy:" + uuid4().hex,
            text=text, source="explicit_user", confirmed=confirmed,
        )

    def memories(self, project_id: str) -> list[dict]:
        from .memory_service import MemoryService
        return [
            {"id": item.id, "project": item.project_id, "text": item.text,
             "source": item.source, "active": 1, "created": item.created.isoformat()}
            for item in MemoryService(self).active_for_project(project_id)
        ]

    def forget(self, project_id: str, memory_id: str) -> None:
        self.project(project_id)
        from .memory_service import MemoryService
        record = MemoryService(self).get(memory_id)
        if record.project_id != project_id:
            raise PermissionError("记忆不存在或无权访问")
        MemoryService(self).revoke(memory_id)

    def feedback(self, run_id: str, kind: str, text: str) -> None:
        self.run(run_id)
        if kind not in {"false_positive", "missed_issue", "bad_advice", "preference"}:
            raise ValueError("忽略操作不是误判反馈")
        with self.connect() as db:
            db.execute(
                "INSERT INTO feedback VALUES(?,?,?,?,?)",
                (uuid4().hex, run_id, kind, text, now()),
            )

    def interrupt_active_runs(self, run_ids=None):
        with self.connect() as db:
            rows = list(
                db.execute(
                    "SELECT r.id FROM runs r JOIN sessions s ON s.id=r.session "
                    "JOIN projects p ON p.id=s.project WHERE p.owner=? "
                    "AND r.state IN ('queued','running','validating')",
                    (self.owner,),
                )
            )
            for row in rows:
                if run_ids is not None and row[0] not in run_ids:
                    continue
                db.execute("UPDATE runs SET state='interrupted' WHERE id=?", (row[0],))
                db.execute(
                    "INSERT INTO events(run,state,detail,created) VALUES(?,?,?,?)",
                    (
                        row[0],
                        "interrupted",
                        "连接终止，本地检查点已保存；服务端任务须核对",
                        now(),
                    ),
                )
