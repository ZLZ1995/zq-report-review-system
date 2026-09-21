"""Versioned additive migrations with a consistent pre-write SQLite backup."""
from __future__ import annotations

import os
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

SCHEMA_VERSION = 14


def _version(db):
    version = db.execute('PRAGMA user_version').fetchone()[0]
    if version > SCHEMA_VERSION:
        raise ValueError('Unsupported local database schema; upgrade the client before opening')
    return version


def apply_v1(db):
    db.execute('''CREATE TABLE IF NOT EXISTS conversation_state (
        session TEXT PRIMARY KEY REFERENCES sessions(id), owner TEXT NOT NULL,
        task_id TEXT, revision INTEGER NOT NULL DEFAULT 1 CHECK(revision > 0),
        question_json TEXT, confirmed_json TEXT NOT NULL DEFAULT '{}',
        cancelled INTEGER NOT NULL DEFAULT 0 CHECK(cancelled IN (0,1)),
        updated TEXT NOT NULL)''')


def apply_v2(db):
    # Separate execute calls preserve the caller's transaction (executescript
    # would implicitly commit it). No customer text or credentials belong here.
    db.execute('''CREATE TABLE IF NOT EXISTS execution_plans (
        run TEXT PRIMARY KEY REFERENCES runs(id),
        revision INTEGER NOT NULL CHECK(revision > 0),
        plan_json TEXT NOT NULL, created TEXT NOT NULL)''')
    db.execute('''CREATE TABLE IF NOT EXISTS execution_steps (
        run TEXT NOT NULL REFERENCES execution_plans(run),
        step_id TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'pending'
          CHECK(state IN ('pending','running','succeeded','failed','cancelled','unknown')),
        attempt INTEGER NOT NULL DEFAULT 0 CHECK(attempt >= 0),
        claim_token TEXT, checkpoint_json TEXT, updated TEXT NOT NULL,
        PRIMARY KEY(run, step_id))''')
    db.execute('''CREATE TABLE IF NOT EXISTS execution_events (
        run TEXT NOT NULL REFERENCES execution_plans(run),
        sequence INTEGER NOT NULL CHECK(sequence > 0),
        step_id TEXT NOT NULL, kind TEXT NOT NULL, dedup_key TEXT NOT NULL,
        created TEXT NOT NULL,
        PRIMARY KEY(run, sequence), UNIQUE(run, dedup_key),
        FOREIGN KEY(run, step_id) REFERENCES execution_steps(run, step_id))''')


def apply_v3(db):
    db.execute('''CREATE TABLE IF NOT EXISTS execution_authorizations (
        run TEXT PRIMARY KEY REFERENCES runs(id), binding_sha256 TEXT NOT NULL,
        confirmation_id TEXT NOT NULL UNIQUE, created TEXT NOT NULL,
        revoked INTEGER NOT NULL DEFAULT 0 CHECK(revoked IN (0,1)))''')


def apply_v4(db):
    db.execute('''CREATE TABLE IF NOT EXISTS execution_results (
        id TEXT PRIMARY KEY, run TEXT NOT NULL, step_id TEXT NOT NULL,
        payload TEXT NOT NULL, sha256 TEXT NOT NULL, created TEXT NOT NULL,
        UNIQUE(run,step_id),
        FOREIGN KEY(run,step_id) REFERENCES execution_steps(run,step_id))''')


def apply_v5(db):
    db.execute('''CREATE TABLE IF NOT EXISTS session_metadata (
        session TEXT PRIMARY KEY REFERENCES sessions(id),
        archived INTEGER NOT NULL DEFAULT 0 CHECK(archived IN (0,1)),
        last_read_message INTEGER NOT NULL DEFAULT 0 CHECK(last_read_message >= 0),
        parent_session TEXT REFERENCES sessions(id),
        fork_message INTEGER REFERENCES messages(id),
        context_snapshot TEXT NOT NULL DEFAULT '{}', updated TEXT NOT NULL)''')
    db.execute('CREATE INDEX IF NOT EXISTS session_parent_idx ON session_metadata(parent_session)')


def apply_v6(db):
    db.execute('''CREATE TABLE IF NOT EXISTS session_drafts (
        session TEXT PRIMARY KEY REFERENCES sessions(id), text TEXT NOT NULL,
        file_ids TEXT NOT NULL DEFAULT '[]',
        submitted INTEGER NOT NULL DEFAULT 0 CHECK(submitted IN (0,1)),
        updated TEXT NOT NULL)''')


def apply_v7(db):
    db.execute('''CREATE TABLE IF NOT EXISTS browser_action_authorizations (
        id TEXT PRIMARY KEY, run TEXT NOT NULL, step_id TEXT NOT NULL,
        binding_sha256 TEXT NOT NULL, created TEXT NOT NULL, expires_at REAL NOT NULL,
        consumed INTEGER NOT NULL DEFAULT 0 CHECK(consumed IN (0,1)),
        UNIQUE(run,binding_sha256),
        FOREIGN KEY(run,step_id) REFERENCES execution_steps(run,step_id))''')


def apply_v8(db):
    db.execute('''CREATE TABLE IF NOT EXISTS browser_download_artifacts (
        id TEXT PRIMARY KEY, run TEXT NOT NULL, step_id TEXT NOT NULL,
        receipt TEXT NOT NULL UNIQUE REFERENCES browser_action_authorizations(id),
        payload TEXT NOT NULL, sha256 TEXT NOT NULL, created TEXT NOT NULL,
        FOREIGN KEY(run,step_id) REFERENCES execution_steps(run,step_id))''')


def apply_v9(db):
    db.execute('''CREATE TABLE IF NOT EXISTS browser_upload_attempts (
        operation_sha256 TEXT PRIMARY KEY,
        receipt TEXT NOT NULL UNIQUE REFERENCES browser_action_authorizations(id),
        run TEXT NOT NULL REFERENCES runs(id),
        state TEXT NOT NULL CHECK(state='unknown'), created TEXT NOT NULL)''')


def apply_v10(db):
    columns = {row[1] for row in db.execute('PRAGMA table_info(browser_upload_attempts)')}
    if 'metadata' not in columns:
        db.execute('ALTER TABLE browser_upload_attempts ADD COLUMN metadata TEXT')


def apply_v11(db):
    db.execute('''CREATE TABLE IF NOT EXISTS memory_records (
        id TEXT PRIMARY KEY, owner TEXT NOT NULL,
        scope TEXT NOT NULL CHECK(scope IN ('user','project','session')),
        project TEXT REFERENCES projects(id), session TEXT REFERENCES sessions(id),
        memory_key TEXT NOT NULL, text TEXT NOT NULL,
        kind TEXT NOT NULL CHECK(kind IN ('preference','fact','instruction')),
        source TEXT NOT NULL CHECK(source IN ('explicit_user','verified_artifact')),
        source_ref TEXT, status TEXT NOT NULL CHECK(status IN ('active','revoked')),
        priority INTEGER NOT NULL CHECK(priority BETWEEN 0 AND 100), valid_until TEXT,
        version INTEGER NOT NULL CHECK(version > 0), created TEXT NOT NULL, updated TEXT NOT NULL)''')
    db.execute('CREATE INDEX IF NOT EXISTS memory_lookup_idx ON memory_records(owner,status,scope,project,session)')
    db.execute('''CREATE TABLE IF NOT EXISTS feedback_records (
        id TEXT PRIMARY KEY, owner TEXT NOT NULL, run TEXT NOT NULL REFERENCES runs(id),
        kind TEXT NOT NULL, summary TEXT NOT NULL, evidence_json TEXT NOT NULL,
        created TEXT NOT NULL)''')
    db.execute('''CREATE TABLE IF NOT EXISTS skill_improvement_proposals (
        id TEXT PRIMARY KEY, owner TEXT NOT NULL,
        feedback_id TEXT NOT NULL UNIQUE REFERENCES feedback_records(id),
        skill_id TEXT NOT NULL, status TEXT NOT NULL CHECK(status IN ('candidate','validated','rejected')),
        summary TEXT NOT NULL, evidence_json TEXT NOT NULL, test_ids_json TEXT NOT NULL,
        created TEXT NOT NULL, updated TEXT NOT NULL)''')
    # Preserve legacy explicit project memories when this is a real platform
    # database.  Very old/synthetic databases may legitimately have neither
    # table; additive migration must still succeed for them.
    tables = {row[0] for row in db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name IN ('memories','projects')"
    )}
    if tables == {'memories', 'projects'}:
        db.execute('''INSERT OR IGNORE INTO memory_records
            (id,owner,scope,project,session,memory_key,text,kind,source,source_ref,status,
             priority,valid_until,version,created,updated)
            SELECT m.id,p.owner,'project',m.project,NULL,'legacy:' || m.id,m.text,'preference',
                   CASE WHEN m.source='explicit_user' THEN 'explicit_user' ELSE 'verified_artifact' END,
                   CASE WHEN m.source='explicit_user' THEN NULL ELSE m.source END,
                   CASE WHEN m.active=1 THEN 'active' ELSE 'revoked' END,
                   50,NULL,1,m.created,m.created
              FROM memories m JOIN projects p ON p.id=m.project''')


def apply_v12(db):
    # Rebuild execution_steps so a step may rest in 'waiting_user' while a run
    # waits for clarification.  The migration connection runs with foreign
    # keys disabled, so drop/rename is safe; child tables resolve the FK by
    # name once the replacement table takes the original name.
    # Very old/synthetic databases may legitimately lack the table; additive
    # migration must still succeed for them.
    if db.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='execution_steps'"
    ).fetchone() is None:
        return
    db.execute('''CREATE TABLE execution_steps_v12 (
        run TEXT NOT NULL REFERENCES execution_plans(run),
        step_id TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'pending'
          CHECK(state IN ('pending','running','succeeded','failed','cancelled',
                          'waiting_user','unknown')),
        attempt INTEGER NOT NULL DEFAULT 0 CHECK(attempt >= 0),
        claim_token TEXT, checkpoint_json TEXT, updated TEXT NOT NULL,
        PRIMARY KEY(run, step_id))''')
    db.execute('''INSERT INTO execution_steps_v12
        (run,step_id,state,attempt,claim_token,checkpoint_json,updated)
        SELECT run,step_id,state,attempt,claim_token,checkpoint_json,updated
        FROM execution_steps''')
    db.execute('DROP TABLE execution_steps')
    db.execute('ALTER TABLE execution_steps_v12 RENAME TO execution_steps')


def apply_v13(db):
    # Pi Agent Core durable session model (S03). Purely additive: ten new
    # agent_* tables; legacy tables are never touched.
    # Deviation from plan section 6 (recorded in the rebuild ledger): lane ids
    # are session-scoped ('main' exists in every session), so agent_lanes uses
    # PRIMARY KEY (session_id, id) and the open-operation partial unique index
    # keys on (session_id, lane_id) instead of lane_id alone.
    db.execute('''CREATE TABLE IF NOT EXISTS agent_sessions (
        id TEXT PRIMARY KEY,
        legacy_session_id TEXT UNIQUE,
        project_id TEXT NOT NULL,
        owner_id TEXT NOT NULL,
        title TEXT NOT NULL,
        schema_version INTEGER NOT NULL,
        status TEXT NOT NULL CHECK(status IN ('active','archived','damaged')),
        default_lane_id TEXT,
        default_model_id TEXT,
        permission_mode TEXT NOT NULL,
        revision INTEGER NOT NULL DEFAULT 1,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        last_activity_at TEXT NOT NULL)''')
    db.execute('''CREATE TABLE IF NOT EXISTS agent_lanes (
        id TEXT NOT NULL,
        session_id TEXT NOT NULL REFERENCES agent_sessions(id),
        name TEXT NOT NULL,
        parent_lane_id TEXT,
        anchor_entry_id TEXT,
        leaf_entry_id TEXT,
        state TEXT NOT NULL CHECK(state IN ('idle','running','suspended','recovering')),
        revision INTEGER NOT NULL DEFAULT 1,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        PRIMARY KEY (session_id, id),
        UNIQUE(session_id, name))''')
    db.execute('''CREATE TABLE IF NOT EXISTS conversation_entries (
        id TEXT PRIMARY KEY,
        session_id TEXT NOT NULL REFERENCES agent_sessions(id),
        lane_id TEXT NOT NULL,
        parent_id TEXT REFERENCES conversation_entries(id),
        sequence INTEGER NOT NULL,
        entry_type TEXT NOT NULL,
        payload_json TEXT NOT NULL,
        operation_id TEXT,
        turn_id TEXT,
        schema_version INTEGER NOT NULL,
        created_at TEXT NOT NULL,
        UNIQUE(session_id, sequence),
        FOREIGN KEY(session_id, lane_id) REFERENCES agent_lanes(session_id, id))''')
    db.execute('''CREATE TABLE IF NOT EXISTS agent_operations (
        id TEXT PRIMARY KEY,
        session_id TEXT NOT NULL REFERENCES agent_sessions(id),
        lane_id TEXT NOT NULL,
        kind TEXT NOT NULL,
        status TEXT NOT NULL,
        request_id TEXT NOT NULL UNIQUE,
        source_entry_id TEXT NOT NULL REFERENCES conversation_entries(id),
        accepted_context_sha256 TEXT NOT NULL,
        model_id TEXT,
        permission_snapshot_json TEXT NOT NULL,
        file_scope_snapshot_json TEXT NOT NULL,
        resource_snapshot_json TEXT NOT NULL,
        current_turn_id TEXT,
        error_code TEXT,
        error_summary TEXT,
        recovery_policy TEXT NOT NULL,
        accepted_at TEXT NOT NULL,
        started_at TEXT,
        finished_at TEXT,
        schema_version INTEGER NOT NULL,
        FOREIGN KEY(session_id, lane_id) REFERENCES agent_lanes(session_id, id))''')
    db.execute('''CREATE UNIQUE INDEX IF NOT EXISTS one_open_operation_per_lane
        ON agent_operations(session_id, lane_id)
        WHERE status IN ('accepted','running','waiting_input','waiting_approval',
                         'deferred','suspended','aborting')''')
    db.execute('''CREATE TABLE IF NOT EXISTS agent_turns (
        id TEXT PRIMARY KEY,
        operation_id TEXT NOT NULL REFERENCES agent_operations(id),
        ordinal INTEGER NOT NULL,
        status TEXT NOT NULL,
        model_request_id TEXT,
        input_context_sha256 TEXT NOT NULL,
        assistant_entry_id TEXT REFERENCES conversation_entries(id),
        started_at TEXT NOT NULL,
        finished_at TEXT,
        error_code TEXT,
        usage_json TEXT,
        UNIQUE(operation_id, ordinal))''')
    db.execute('''CREATE TABLE IF NOT EXISTS agent_tool_calls (
        id TEXT PRIMARY KEY,
        operation_id TEXT NOT NULL REFERENCES agent_operations(id),
        turn_id TEXT NOT NULL REFERENCES agent_turns(id),
        tool_name TEXT NOT NULL,
        arguments_json TEXT NOT NULL,
        arguments_sha256 TEXT NOT NULL,
        risk_level TEXT NOT NULL,
        authorization_id TEXT,
        status TEXT NOT NULL,
        result_entry_id TEXT REFERENCES conversation_entries(id),
        idempotency_key TEXT NOT NULL UNIQUE,
        started_at TEXT,
        finished_at TEXT,
        error_code TEXT)''')
    db.execute('''CREATE TABLE IF NOT EXISTS agent_operation_events (
        sequence INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id TEXT NOT NULL,
        lane_id TEXT NOT NULL,
        operation_id TEXT,
        turn_id TEXT,
        tool_call_id TEXT,
        event_type TEXT NOT NULL,
        payload_json TEXT NOT NULL,
        created_at TEXT NOT NULL)''')
    db.execute('''CREATE TABLE IF NOT EXISTS turn_file_bindings (
        operation_id TEXT NOT NULL REFERENCES agent_operations(id),
        file_id TEXT NOT NULL,
        binding_kind TEXT NOT NULL,
        source_entry_id TEXT,
        role TEXT,
        sha256 TEXT NOT NULL,
        PRIMARY KEY(operation_id, file_id, binding_kind))''')
    db.execute('''CREATE TABLE IF NOT EXISTS project_facts (
        id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL,
        scope TEXT NOT NULL,
        fact_key TEXT NOT NULL,
        value_json TEXT NOT NULL,
        source_entry_id TEXT,
        confidence REAL,
        status TEXT NOT NULL CHECK(status IN ('proposed','confirmed','rejected','superseded')),
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL)''')
    db.execute('''CREATE TABLE IF NOT EXISTS context_compactions (
        id TEXT PRIMARY KEY,
        session_id TEXT NOT NULL,
        lane_id TEXT NOT NULL,
        source_start_entry_id TEXT NOT NULL,
        source_end_entry_id TEXT NOT NULL,
        source_sha256 TEXT NOT NULL,
        summary_entry_id TEXT NOT NULL,
        created_at TEXT NOT NULL)''')


def apply_v14(db):
    """S16：run ↔ message 归属关联表 + 历史回填（诚实标注，不伪造精确归属）。"""
    db.execute('''CREATE TABLE IF NOT EXISTS run_message_links (
        run_id TEXT PRIMARY KEY REFERENCES runs(id),
        session_id TEXT NOT NULL REFERENCES sessions(id),
        source_message_id INTEGER REFERENCES messages(id),
        assistant_message_id INTEGER REFERENCES messages(id),
        relation TEXT NOT NULL CHECK(relation IN ('exact','legacy_inferred','legacy_unlinked')),
        created_at TEXT NOT NULL)''')
    db.execute('''CREATE INDEX IF NOT EXISTS run_message_links_by_assistant
        ON run_message_links(session_id, assistant_message_id)''')
    tables = {row[0] for row in db.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    if not {'runs', 'messages', 'events'} <= tables:
        return  # 纯旧版库没有业务表：只建空表，回填留给数据存在时
    _backfill_run_message_links(db)


def _backfill_run_message_links(db):
    """历史 run 归属回填：顺序 + 唯一性同时成立才标 legacy_inferred。

    - 候选 = run 终态（events 末条 created，无事件用 runs.created）之后
      同会话最近的一条 assistant 消息；
    - 同一候选被多个待回填 run 指向 → 全部 legacy_unlinked（不伪造归属）；
    - 幂等：已有关联的 run 跳过，重放迁移不产生重复或改写；
    - 审计数量经 relation 标签永久可查（exact/inferred/unlinked）。
    """
    linked = {row[0] for row in db.execute('SELECT run_id FROM run_message_links')}
    runs = db.execute(
        'SELECT id, session, created FROM runs ORDER BY created, id').fetchall()
    pending = [row for row in runs if row[0] not in linked]
    candidates = {}
    for run_id, session, created in pending:
        terminal = db.execute(
            'SELECT MAX(created) FROM events WHERE run=?', (run_id,)).fetchone()[0]
        terminal = terminal or created
        candidate = db.execute(
            "SELECT id FROM messages WHERE session=? AND role='assistant' "
            'AND created>=? ORDER BY created, id LIMIT 1',
            (session, terminal)).fetchone()
        candidates[run_id] = (session, created, candidate[0] if candidate else None)
    shares = {}
    for _session, _created, candidate in candidates.values():
        if candidate is not None:
            shares[candidate] = shares.get(candidate, 0) + 1
    stamp = datetime.now(timezone.utc).isoformat()
    for run_id, (session, created, candidate) in candidates.items():
        if candidate is None or shares.get(candidate, 0) > 1:
            relation, assistant_id, source_id = 'legacy_unlinked', None, None
        else:
            relation, assistant_id = 'legacy_inferred', candidate
            source = db.execute(
                "SELECT id FROM messages WHERE session=? AND role='user' "
                'AND created<=? ORDER BY created DESC, id DESC LIMIT 1',
                (session, created)).fetchone()
            source_id = source[0] if source else None
        db.execute(
            'INSERT INTO run_message_links(run_id, session_id, source_message_id,'
            ' assistant_message_id, relation, created_at) VALUES(?,?,?,?,?,?)',
            (run_id, session, source_id, assistant_id, relation, stamp))


def migrate_database(path: Path) -> Path | None:
    path = path.resolve()
    if not path.is_file():
        raise OSError('Database is missing; refusing to recreate it')
    with closing(sqlite3.connect(path.as_uri() + '?mode=rw', uri=True, timeout=15)) as db:
        if _version(db) == SCHEMA_VERSION:
            return None
        if path.drive and path.drive.casefold() == os.environ.get('SystemDrive', 'C:').casefold():
            raise ValueError('Migration backup requires a non-system data directory')
        db.execute('BEGIN IMMEDIATE')
        try:
            # Another opener may have completed the migration before this lock.
            previous_version = _version(db)
            if previous_version == SCHEMA_VERSION:
                db.rollback()
                return None
            has_runs = db.execute("SELECT name FROM sqlite_master WHERE name='runs'").fetchone()
            if has_runs and db.execute(
                "SELECT 1 FROM runs WHERE state IN ('queued','running','validating') LIMIT 1"
            ).fetchone():
                raise ValueError('Resolve active tasks before migrating the local database')
            folder = path.parent / 'migration-backups'
            if folder.resolve() != folder:
                raise ValueError('Migration backup directory must not redirect through a link')
            folder.mkdir(exist_ok=True)
            backup = folder / f'{path.stem}-v{previous_version}-{uuid4().hex}.sqlite'
            backup.touch(exist_ok=False)
            # The writer holds a reservation but has not written yet. A separate
            # read connection gives backup() a consistent snapshot without trying
            # to back up a connection inside its own write transaction.
            with (
                closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)) as source,
                closing(sqlite3.connect(backup)) as destination,
            ):
                source.backup(destination)
                if destination.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
                    raise ValueError('Migration backup failed integrity validation')
            if previous_version < 1:
                apply_v1(db)
            if previous_version < 2:
                apply_v2(db)
            if previous_version < 3:
                apply_v3(db)
            if previous_version < 4:
                apply_v4(db)
            if previous_version < 5:
                apply_v5(db)
            if previous_version < 6:
                apply_v6(db)
            if previous_version < 7:
                apply_v7(db)
            if previous_version < 8:
                apply_v8(db)
            if previous_version < 9:
                apply_v9(db)
            if previous_version < 10:
                apply_v10(db)
            if previous_version < 11:
                apply_v11(db)
            if previous_version < 12:
                apply_v12(db)
            if previous_version < 13:
                apply_v13(db)
            if previous_version < 14:
                apply_v14(db)
            db.execute(f'PRAGMA user_version={SCHEMA_VERSION}')
            db.commit()
            return backup
        except BaseException:
            db.rollback()
            raise
