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
    def __init__(self, path: Path, owner: str) -> None:
        if not owner.strip():
            raise ValueError("owner is required")
        path.parent.mkdir(parents=True, exist_ok=True)
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

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
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
        self.project(project_id)
        with self.connect() as db:
            return [
                dict(r)
                for r in db.execute(
                    "SELECT * FROM sessions WHERE project=? ORDER BY created",
                    (project_id,),
                )
            ]

    def append(self, session_id: str, role: str, text: str) -> None:
        self.session(session_id)
        if role not in {"user", "assistant", "event"}:
            raise ValueError("invalid message role")
        with self.connect() as db:
            db.execute(
                "INSERT INTO messages(session,role,text,created) VALUES(?,?,?,?)",
                (session_id, role, text, now()),
            )

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
            if snapshot["schema_version"] != 1:
                raise ValueError("不支持的任务版本")
            if (snapshot.get("owner") != self.owner
                    or snapshot.get("session_id") != session_id
                    or snapshot.get("project_id") != session["project"]):
                raise PermissionError("任务归属与当前会话不一致")
            identity = snapshot["task_id"]
        with self.connect() as db:
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
            "running": {"validating", "cancelled", "failed"},
            "validating": {"succeeded", "failed", "cancelled"},
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

    def save_result(self, run_id: str, result: dict) -> None:
        self.run(run_id)
        with self.connect() as db:
            db.execute(
                "UPDATE runs SET result=? WHERE id=?",
                (json.dumps(result, ensure_ascii=False), run_id),
            )

    def remember(self, project_id: str, text: str, *, confirmed: bool) -> str:
        self.project(project_id)
        if not confirmed or not text.strip():
            raise ValueError("记忆必须由用户明确确认")
        identity = uuid4().hex
        with self.connect() as db:
            db.execute(
                "INSERT INTO memories VALUES(?,?,?,?,1,?)",
                (identity, project_id, text.strip(), "explicit_user", now()),
            )
        return identity

    def memories(self, project_id: str) -> list[dict]:
        self.project(project_id)
        with self.connect() as db:
            return [
                dict(r)
                for r in db.execute(
                    "SELECT * FROM memories WHERE project=? AND active=1 ORDER BY created",
                    (project_id,),
                )
            ]

    def forget(self, project_id: str, memory_id: str) -> None:
        self.project(project_id)
        with self.connect() as db:
            db.execute(
                "DELETE FROM memories WHERE project=? AND id=?", (project_id, memory_id)
            )

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
