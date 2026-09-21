"""Create, inspect and revoke user-confirmed memories without changing history."""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from .memory_contracts import MemoryRecord


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def _required_time(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _record(row) -> MemoryRecord:
    return MemoryRecord(
        id=row["id"], owner=row["owner"], scope=row["scope"], key=row["memory_key"],
        text=row["text"], kind=row["kind"], source=row["source"],
        source_ref=row["source_ref"], status=row["status"], priority=row["priority"],
        project_id=row["project"], session_id=row["session"],
        valid_until=_parse(row["valid_until"]), version=row["version"],
        created=_required_time(row["created"]), updated=_required_time(row["updated"]),
    )


class MemoryService:
    def __init__(self, store, *, clock=_utc_now):
        self.store = store
        self.clock = clock

    def _scope(self, scope, project_id, session_id):
        if scope not in {"user", "project", "session"}:
            raise ValueError("Invalid memory scope")
        if scope == "user":
            if project_id is not None or session_id is not None:
                raise ValueError("User memory cannot bind a project or session")
            return
        if not project_id:
            raise ValueError("Project-scoped memory requires a project")
        self.store.project(project_id)
        if scope == "project" and session_id is not None:
            raise ValueError("Project memory cannot bind a session")
        if (scope == "session"
                and (not session_id or self.store.session(session_id)["project"] != project_id)):
            raise PermissionError("Session is not inside the selected project")

    def create(self, *, scope, key, text, confirmed, project_id=None, session_id=None,
               kind="preference", source="explicit_user", source_ref=None,
               expires_at=None, priority=50):
        if not confirmed:
            raise ValueError("Memory requires explicit user confirmation")
        self._scope(scope, project_id, session_id)
        key, text = key.strip(), text.strip()
        if not key or len(key) > 128 or not text or len(text) > 2000:
            raise ValueError("Memory key or text is invalid")
        if kind not in {"preference", "fact", "instruction"}:
            raise ValueError("Invalid memory kind")
        if source not in {"explicit_user", "verified_artifact"}:
            raise ValueError("Invalid memory source")
        if source == "verified_artifact" and not source_ref:
            raise ValueError("Verified artifact memory requires a source reference")
        if type(priority) is not int or not 0 <= priority <= 100:
            raise ValueError("Memory priority must be between 0 and 100")
        if expires_at is not None:
            if not isinstance(expires_at, datetime) or expires_at.tzinfo is None:
                raise ValueError("Memory expiry must be timezone-aware")
            expires_at = expires_at.astimezone(timezone.utc).isoformat()
        identity, timestamp = uuid4().hex, self.clock().astimezone(timezone.utc).isoformat()
        with self.store.connect() as db:
            db.execute(
                "INSERT INTO memory_records(id,owner,scope,project,session,memory_key,text,kind,"
                "source,source_ref,status,priority,valid_until,version,created,updated) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,'active',?,?,1,?,?)",
                (identity, self.store.owner, scope, project_id, session_id, key, text, kind,
                 source, source_ref, priority, expires_at, timestamp, timestamp),
            )
        return identity

    def get(self, identity):
        with self.store.connect() as db:
            row = db.execute("SELECT * FROM memory_records WHERE id=? AND owner=?",
                             (identity, self.store.owner)).fetchone()
        if row is None:
            raise PermissionError("Memory does not exist or is not accessible")
        return _record(row)

    def revoke(self, identity):
        self.get(identity)
        timestamp = self.clock().astimezone(timezone.utc).isoformat()
        with self.store.connect() as db:
            db.execute("UPDATE memory_records SET status='revoked',version=version+1,updated=? "
                       "WHERE id=? AND owner=?", (timestamp, identity, self.store.owner))

    def active_for_project(self, project_id):
        self.store.project(project_id)
        current = self.clock().astimezone(timezone.utc).isoformat()
        with self.store.connect() as db:
            rows = db.execute(
                "SELECT * FROM memory_records WHERE owner=? AND project=? AND status='active' "
                "AND (valid_until IS NULL OR valid_until>?) ORDER BY created,id",
                (self.store.owner, project_id, current),
            ).fetchall()
        return [_record(row) for row in rows]

    def list_for_context(self, session_id, *, include_revoked=True):
        session = self.store.session(session_id)
        project_id = session["project"]
        condition = "" if include_revoked else " AND status='active'"
        with self.store.connect() as db:
            rows = db.execute(
                "SELECT * FROM memory_records WHERE owner=? AND (scope='user' OR "
                "(scope='project' AND project=?) OR "
                "(scope='session' AND project=? AND session=?))" + condition +
                " ORDER BY updated DESC,id DESC",
                (self.store.owner, project_id, project_id, session_id),
            ).fetchall()
        return [_record(row) for row in rows]
