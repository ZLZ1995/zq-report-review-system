"""Durable update transitions, not an installer or a health-check substitute.

Only trusted installer code calls transition methods while holding the installation
lock. No model/browser tool exposes these methods. Backup/health digests must come
from real verification; a matching digest alone does not verify a running EXE.
"""

import re
import sqlite3
from collections.abc import Mapping
from contextlib import closing, contextmanager
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

from .manifest import UpdatePolicy, verify_manifest, version_tuple
from .process_lock import InstallationLock
from .trusted_keys import PUBLIC_KEYS, REVOKED_KEY_IDS


class UpdateJournal:
    def __init__(self, path: Path, policy: UpdatePolicy, *, keys: Mapping[str, bytes] = PUBLIC_KEYS):
        self.path = path
        self.policy = policy
        self.keys = keys

    @staticmethod
    def initialize(path: Path, policy: UpdatePolicy) -> None:
        InstallationLock._validate(path)
        version_tuple(policy.current_version)
        if type(policy.last_sequence) is not int or policy.last_sequence < 0:
            raise ValueError('Invalid initial release sequence')
        with path.open('xb'):
            pass
        with closing(sqlite3.connect(path.as_uri() + '?mode=rw', uri=True)) as db, db:
            db.execute('''CREATE TABLE update_state (
                id INTEGER PRIMARY KEY CHECK(id=1), active_version TEXT NOT NULL,
                sequence INTEGER NOT NULL CHECK(sequence>=0), phase TEXT NOT NULL
                CHECK(phase IN ('idle','prepared','backed_up','activating','recovery_required')),
                token TEXT, signed_manifest BLOB, target_version TEXT, target_sequence INTEGER,
                package_sha256 TEXT, backup_sha256 TEXT)''')
            db.execute("INSERT INTO update_state(id,active_version,sequence,phase) VALUES(1,?,?,'idle')",
                       (policy.current_version, policy.last_sequence))
            db.execute('''CREATE TABLE update_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT, token TEXT NOT NULL,
                event TEXT NOT NULL, version TEXT NOT NULL)''')
            db.execute('PRAGMA user_version=1')

    @contextmanager
    def _transaction(self):
        InstallationLock._validate(self.path)
        if not self.path.is_file():
            raise FileNotFoundError('Update journal missing; repair required')
        with closing(sqlite3.connect(self.path.as_uri() + '?mode=rw', uri=True, timeout=0)) as db, db:
            db.row_factory = sqlite3.Row
            db.execute('PRAGMA synchronous=FULL')
            db.execute('BEGIN IMMEDIATE')
            if db.execute('PRAGMA user_version').fetchone()[0] != 1:
                raise ValueError('Unsupported update journal')
            row = db.execute('SELECT * FROM update_state WHERE id=1').fetchone()
            if row is None:
                raise ValueError('Incomplete update journal')
            yield db, dict(row)

    def snapshot(self) -> dict:
        with self._transaction() as (_, row):
            # Signed payload is public but not needed in UI state summaries.
            return {key: value for key, value in row.items() if key != 'signed_manifest'}

    def launch_version(self) -> str:
        row = self.snapshot()
        if row['phase'] != 'idle':
            raise ValueError('Unfinished update requires recovery before launch')
        version_tuple(row['active_version'])
        return row['active_version']

    @staticmethod
    def _event(db, token: str, kind: str, version: str) -> None:
        db.execute('INSERT INTO update_events(token,event,version) VALUES(?,?,?)', (token, kind, version))

    def begin(self, raw: bytes, *, now: int) -> str:
        with self._transaction() as (db, row):
            if row['phase'] != 'idle':
                raise ValueError('An update is already pending')
            policy = replace(self.policy, current_version=row['active_version'], last_sequence=row['sequence'])
            release = verify_manifest(raw, keys=self.keys, policy=policy, now=now, revoked_keys=REVOKED_KEY_IDS)
            token = uuid4().hex
            db.execute('''UPDATE update_state SET phase='prepared',token=?,signed_manifest=?,
                       target_version=?,target_sequence=?,package_sha256=?,backup_sha256=NULL WHERE id=1''',
                       (token, raw, release.version, release.sequence, release.sha256))
            self._event(db, token, 'prepared', release.version)
            return token

    @staticmethod
    def _require(row: dict, token: str, phases: tuple[str, ...]) -> None:
        if not token or token != row['token'] or row['phase'] not in phases:
            raise ValueError('Stale update token or invalid transition')

    def backup_verified(self, token: str, *, backup_sha256: str) -> None:
        if not isinstance(backup_sha256, str) or not re.fullmatch(r'[0-9a-f]{64}', backup_sha256):
            raise ValueError('Verified backup digest required')
        with self._transaction() as (db, row):
            self._require(row, token, ('prepared',))
            db.execute("UPDATE update_state SET phase='backed_up',backup_sha256=? WHERE id=1", (backup_sha256,))
            self._event(db, token, 'backed_up', row['target_version'])

    def activating(self, token: str) -> None:
        with self._transaction() as (db, row):
            self._require(row, token, ('backed_up',))
            db.execute("UPDATE update_state SET phase='activating' WHERE id=1")
            self._event(db, token, 'activating', row['target_version'])

    def complete(self, token: str, *, package_sha256: str) -> None:
        with self._transaction() as (db, row):
            self._require(row, token, ('activating',))
            if package_sha256 != row['package_sha256']:
                raise ValueError('Health check package does not match pending release')
            db.execute('''UPDATE update_state SET active_version=target_version,sequence=target_sequence,
                       phase='idle',token=NULL,target_version=NULL,target_sequence=NULL,
                       package_sha256=NULL,backup_sha256=NULL,signed_manifest=NULL WHERE id=1''')
            self._event(db, token, 'healthy', row['target_version'])

    def fail(self, token: str) -> None:
        with self._transaction() as (db, row):
            self._require(row, token, ('prepared', 'backed_up', 'activating'))
            if row['phase'] == 'activating':
                db.execute("UPDATE update_state SET phase='recovery_required' WHERE id=1")
            else:
                db.execute('''UPDATE update_state SET phase='idle',token=NULL,target_version=NULL,
                           target_sequence=NULL,package_sha256=NULL,backup_sha256=NULL,
                           signed_manifest=NULL WHERE id=1''')
            self._event(db, token, 'failed_' + row['phase'], row['target_version'])

    def recovery_verified(self, token: str, *, backup_sha256: str) -> None:
        """Trusted recovery caller has verified all live data is unchanged."""
        with self._transaction() as (db, row):
            self._require(row, token, ('recovery_required',))
            if backup_sha256 != row['backup_sha256']:
                raise ValueError('Recovery evidence does not match update backup')
            db.execute('''UPDATE update_state SET phase='idle',token=NULL,target_version=NULL,
                       target_sequence=NULL,package_sha256=NULL,backup_sha256=NULL,
                       signed_manifest=NULL WHERE id=1''')
            self._event(db, token, 'recovered_unchanged_data', row['active_version'])

