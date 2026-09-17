"""Immutable local step results, separate from event metadata and scoped by owner."""
import json
from hashlib import sha256
from uuid import uuid4

from .event_store import ExecutionStore
from .store import now


class StepResults:
    def __init__(self, store):
        self.store = store

    def save(self, run_id, step_id, result):
        payload = json.dumps(result, sort_keys=True, ensure_ascii=False, allow_nan=False)
        if len(payload.encode('utf-8')) > 4_000_000:
            raise ValueError('Step result exceeds local storage limit')
        digest = sha256(payload.encode('utf-8')).hexdigest()
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            run = ExecutionStore(self.store)._run(db, run_id)
            step = db.execute('SELECT state FROM execution_steps WHERE run=? AND step_id=?',
                              (run_id, step_id)).fetchone()
            if run['state'] != 'running' or step is None or step['state'] != 'running':
                raise PermissionError('Result does not belong to an active step')
            previous = db.execute('SELECT id,sha256 FROM execution_results WHERE run=? AND step_id=?',
                                  (run_id, step_id)).fetchone()
            if previous:
                if previous['sha256'] != digest:
                    raise ValueError('Step result is immutable')
                return previous['id']
            identity = uuid4().hex
            db.execute('INSERT INTO execution_results VALUES(?,?,?,?,?,?)',
                       (identity, run_id, step_id, payload, digest, now()))
            return identity

    def read(self, run_id, step_id, identity):
        with self.store.connect() as db:
            ExecutionStore(self.store)._run(db, run_id)
            row = db.execute('SELECT payload,sha256 FROM execution_results WHERE id=? AND run=? AND step_id=?',
                             (identity, run_id, step_id)).fetchone()
            if row is None:
                raise PermissionError('Step result not found in this scope')
            if sha256(row['payload'].encode('utf-8')).hexdigest() != row['sha256']:
                raise ValueError('Step result integrity check failed')
            return json.loads(row['payload'])
