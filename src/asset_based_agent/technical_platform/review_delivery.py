"""Scoped follow-up view; immutable step results remain separate from delivery metadata."""
import json

from .artifact_registry import resolve_step_inputs
from .execution_plan import ExecutionPlan
from .plan_results import completed_step_results

_DELIVERY_FIELDS = frozenset({'exported_report', 'annotations', 'annotation_prompted', 'delivery_versions'})


def step_review_store(store, session_id, run_id, ordinal):
    view = StepReviewStore(store, session_id, run_id, ordinal)
    view.run(run_id)  # Reject invalid scope before showing a dialog or creating output.
    return view


class StepReviewStore:
    def __init__(self, store, session_id, run_id, ordinal):
        self.store, self.session_id, self.run_id, self.ordinal = store, session_id, run_id, ordinal
        self.path, self.owner = store.path, store.owner

    def _context(self, run_id):
        if run_id != self.run_id:
            raise PermissionError('Delivery belongs to a different task')
        records = completed_step_results(self.store, self.session_id, run_id)
        if type(self.ordinal) is not int or not 0 <= self.ordinal < len(records):
            raise ValueError('Invalid review step index')
        record = records[self.ordinal]
        if record['result'].get('kind') != 'review':
            raise ValueError('Only a completed review step can produce review deliverables')
        run = dict(self.store.run(run_id))
        snapshot = json.loads(run['snapshot'])
        step = ExecutionPlan.model_validate(snapshot['execution_plan']).steps[self.ordinal]
        files = resolve_step_inputs(self.store, run_id, step)
        return run, snapshot, record, files

    def run(self, run_id):
        run, snapshot, record, files = self._context(run_id)
        metadata = json.loads(run['result']).get('review_deliveries', {}).get(record['step_id'], {})
        if not isinstance(metadata, dict) or not set(metadata) <= _DELIVERY_FIELDS:
            raise PermissionError('Invalid review delivery metadata')
        run['snapshot'] = json.dumps({**snapshot, 'files': files}, ensure_ascii=False)
        run['result'] = json.dumps({**record['result'], **metadata}, ensure_ascii=False)
        return run

    def save_result(self, run_id, result):
        _, _, record, _ = self._context(run_id)
        unchanged = {k: v for k, v in result.items() if k not in _DELIVERY_FIELDS}
        if unchanged != record['result']:
            raise PermissionError('Review results are immutable; only follow-up metadata can change')
        # Merge only this step under the same write transaction; never replace checkpoints.
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT result,state,session FROM runs WHERE id=?', (run_id,)).fetchone()
            if row is None or row['state'] != 'succeeded' or row['session'] != self.session_id:
                raise PermissionError('Review task state changed')
            parent = json.loads(row['result'])
            parent.setdefault('review_deliveries', {})[record['step_id']] = {
                k: v for k, v in result.items() if k in _DELIVERY_FIELDS}
            db.execute('UPDATE runs SET result=? WHERE id=?', (json.dumps(parent, ensure_ascii=False), run_id))

    def session(self, identity):
        if identity != self.session_id:
            raise PermissionError('Delivery belongs to a different session')
        return self.store.session(identity)

    def project(self, identity):
        return self.store.project(identity)

    def files(self, identity):
        return self.store.files(identity)
