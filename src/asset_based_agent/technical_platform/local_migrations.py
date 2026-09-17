"""Versioned additive migrations with a consistent pre-write SQLite backup."""
from __future__ import annotations

import os
import sqlite3
from contextlib import closing
from pathlib import Path
from uuid import uuid4

SCHEMA_VERSION = 10


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
            db.execute(f'PRAGMA user_version={SCHEMA_VERSION}')
            db.commit()
            return backup
        except BaseException:
            db.rollback()
            raise
