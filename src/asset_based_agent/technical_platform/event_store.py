"""Transactional plan claims and replayable metadata, never execution authority.

No expired-claim stealing: a running step may have reached a paid remote service.
Recovery must reconcile that service before considering another execution.
"""
import json
from hashlib import sha256
from uuid import uuid4

from .execution_plan import ExecutionPlan
from .store import now
from .task_spec import snapshot_identity


class ExecutionStore:
    def __init__(self, store):
        self.store = store

    def _run(self, db, run_id):
        row = db.execute(
            'SELECT r.*,s.project FROM runs r JOIN sessions s ON s.id=r.session '
            'JOIN projects p ON p.id=s.project WHERE r.id=? AND p.owner=?',
            (run_id, self.store.owner),
        ).fetchone()
        if row is None:
            raise PermissionError('Task is unavailable to this account')
        return row

    def register(self, plan: ExecutionPlan):
        # Revalidate even a model_copy-built object; never trust caller mutation.
        plan = ExecutionPlan.model_validate(plan.model_dump())
        run_id = plan.identity.task_id
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            run = self._run(db, run_id)
            snapshot = json.loads(run['snapshot'])
            if (plan.identity != snapshot_identity(snapshot)
                    or plan.identity.owner != self.store.owner
                    or plan.identity.session_id != run['session']
                    or plan.identity.project_id != run['project']
                    or ExecutionPlan.model_validate(snapshot.get('execution_plan')) != plan):
                raise PermissionError('Plan does not match the recorded task')
            existing = db.execute('SELECT plan_json FROM execution_plans WHERE run=?', (run_id,)).fetchone()
            if existing:
                if ExecutionPlan.model_validate_json(existing[0]) != plan:
                    raise PermissionError('Registered plan is immutable')
                return
            if run['state'] != 'running':
                raise ValueError('Task must be claimed before plan registration')
            db.execute('INSERT INTO execution_plans VALUES(?,?,?,?)',
                       (run_id, plan.revision, plan.model_dump_json(), now()))
            for step in plan.steps:
                db.execute('INSERT INTO execution_steps(run,step_id,updated) VALUES(?,?,?)',
                           (run_id, step.step_id, now()))

    @staticmethod
    def _event(db, run_id, step_id, kind, key):
        sequence = db.execute(
            'SELECT COALESCE(MAX(sequence),0)+1 FROM execution_events WHERE run=?',
            (run_id,),
        ).fetchone()[0]
        db.execute('INSERT INTO execution_events VALUES(?,?,?,?,?,?)',
                   (run_id, sequence, step_id, kind, key, now()))

    def claim(self, run_id, step_id):
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            run = self._run(db, run_id)
            if run['state'] != 'running':
                raise ValueError('Task is not running')
            row = db.execute('SELECT plan_json FROM execution_plans WHERE run=?', (run_id,)).fetchone()
            if row is None:
                raise ValueError('Plan is not registered')
            plan = ExecutionPlan.model_validate_json(row[0])
            states = {r['step_id']: r['state'] for r in db.execute(
                'SELECT step_id,state FROM execution_steps WHERE run=?', (run_id,))}
            completed = {key for key, state in states.items() if state == 'succeeded'}
            if states.get(step_id) != 'pending' or step_id not in plan.ready_steps(completed):
                raise ValueError('Step is not ready or already claimed')
            token = uuid4().hex
            db.execute("UPDATE execution_steps SET state='running',attempt=attempt+1,"
                       'claim_token=?,updated=? WHERE run=? AND step_id=?',
                       (token, now(), run_id, step_id))
            self._event(db, run_id, step_id, 'running', 'claim:' + token)
            return token

    def record_run_terminal(self, run_id, claim_token):
        """Bridge the existing single-adapter executor's authoritative outcome.

        Multi-step outcomes must be validated individually by the future dispatcher;
        a whole-run success is not evidence that each arbitrary step succeeded.
        """
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            run = self._run(db, run_id)
            steps = db.execute('SELECT * FROM execution_steps WHERE run=?', (run_id,)).fetchall()
            if len(steps) != 1:
                raise ValueError('Terminal bridge requires exactly one step')
            step = steps[0]
            if not claim_token or step['claim_token'] != claim_token:
                raise PermissionError('Step claim does not belong to this executor')
            if run['state'] not in {'succeeded', 'failed', 'cancelled'}:
                raise ValueError('Run outcome is not terminal; do not retry the tool')
            if step['state'] == run['state']:
                return
            if step['state'] != 'running':
                raise ValueError('Step is not running')
            # Reference the existing result; do not duplicate customer text.
            checkpoint = json.dumps({'run_id': run_id, 'state': run['state']})
            db.execute('UPDATE execution_steps SET state=?,checkpoint_json=?,updated=? '
                       'WHERE run=? AND step_id=?',
                       (run['state'], checkpoint, now(), run_id, step['step_id']))
            self._event(db, run_id, step['step_id'], run['state'], 'terminal:' + claim_token)

    def events(self, run_id, *, after=0):
        if type(after) is not int or after < 0:
            raise ValueError('Invalid event cursor')
        with self.store.connect() as db:
            self._run(db, run_id)
            return [dict(row) for row in db.execute(
                'SELECT run,sequence,step_id,kind,created FROM execution_events '
                'WHERE run=? AND sequence>? ORDER BY sequence LIMIT 1000', (run_id, after))]

    def finish_step(self, run_id, step_id, token, outcome):
        from .tool_dispatcher import validate_outcome

        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            run = self._run(db, run_id)
            plan_row = db.execute('SELECT plan_json FROM execution_plans WHERE run=?', (run_id,)).fetchone()
            if plan_row is None:
                raise ValueError('Plan is missing')
            plan = ExecutionPlan.model_validate_json(plan_row[0])
            step = next((step for step in plan.steps if step.step_id == step_id), None)
            if step is None:
                raise ValueError('Unknown step')
            outcome = validate_outcome(step, outcome)
            if outcome.result_ref is not None:
                result = db.execute('SELECT payload,sha256 FROM execution_results '
                                    'WHERE id=? AND run=? AND step_id=?',
                                    (outcome.result_ref, run_id, step_id)).fetchone()
                if result is None:
                    raise PermissionError('Step result reference is outside this execution')
                if sha256(result['payload'].encode('utf-8')).hexdigest() != result['sha256']:
                    raise ValueError('Step result integrity check failed')
            row = db.execute('SELECT * FROM execution_steps WHERE run=? AND step_id=?',
                             (run_id, step_id)).fetchone()
            if row is None or not token or row['claim_token'] != token:
                raise PermissionError('Step claim belongs to another executor')
            encoded = outcome.model_dump_json()
            if row['state'] == outcome.status and row['checkpoint_json'] == encoded:
                return
            if row['state'] != 'running' or run['state'] != 'running':
                raise ValueError('Step no longer accepts a result')
            db.execute('UPDATE execution_steps SET state=?,checkpoint_json=?,updated=? '
                       'WHERE run=? AND step_id=?',
                       (outcome.status, encoded, now(), run_id, step_id))
            self._event(db, run_id, step_id, outcome.status, 'outcome:' + token)
