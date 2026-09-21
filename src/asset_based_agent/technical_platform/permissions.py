"""Local consent receipts issued by the trusted UI, never by a model response.

Receipts bind all task inputs/actions/versions plus the resolved output root.
They are not a defence against a user who edits their own SQLite database.
"""
import json
import time
from hashlib import sha256
from uuid import uuid4

from .event_store import ExecutionStore
from .store import now


class PermissionService:
    def __init__(self, store):
        self.store = store
        self.executions = ExecutionStore(store)

    def _binding(self, snapshot):
        # Execution-time memory is refreshed separately, never execution authority.
        # The material-resolution override is likewise excluded: it is written
        # only while the run waits for clarification and is validated against
        # the persisted candidate set before use, so it cannot widen scope.
        excluded = {'execution_context', 'material_resolution_override'}
        bound = {key: value for key, value in snapshot.items() if key not in excluded}
        payload = {'snapshot': bound, 'output_root': str(self.store.path.parent.resolve())}
        return sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False,
                                 allow_nan=False).encode('utf-8')).hexdigest()

    def authorize(self, run_id, confirmed_snapshot, *, confirmed):
        if confirmed is not True:
            raise PermissionError('Explicit confirmation is required')
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            run = self.executions._run(db, run_id)
            recorded = json.loads(run['snapshot'])
            if (type(recorded.get('schema_version')) is not int or recorded['schema_version'] != 2
                    or run['state'] != 'queued' or recorded != confirmed_snapshot):
                raise PermissionError('Task changed after confirmation')
            if recorded.get('permissions', {}).get('modify_originals') is not False:
                raise PermissionError('Original modification is not authorized')
            binding = self._binding(recorded)
            previous = db.execute('SELECT * FROM execution_authorizations WHERE run=?', (run_id,)).fetchone()
            if previous:
                if previous['revoked'] or previous['binding_sha256'] != binding:
                    raise PermissionError('Existing authorization is invalid; submit a new task')
                return previous['confirmation_id']
            confirmation = uuid4().hex
            db.execute('INSERT INTO execution_authorizations VALUES(?,?,?,?,0)',
                       (run_id, binding, confirmation, now()))
            return confirmation

    def verify(self, run_id):
        with self.store.connect() as db:
            self._verify(db, run_id)

    def _verify(self, db, run_id):
        run = self.executions._run(db, run_id)
        receipt = db.execute('SELECT * FROM execution_authorizations WHERE run=?', (run_id,)).fetchone()
        if (receipt is None or receipt['revoked'] or run['state'] not in {'queued', 'running', 'validating'}
                or receipt['binding_sha256'] != self._binding(json.loads(run['snapshot']))):
            raise PermissionError('Task authorization is missing, revoked or out of scope')
        return run

    def _browser_binding(self, db, request):
        from .browser_action_request import BrowserActionRequest
        from .browser_task_spec import BrowserTaskScope
        from .execution_plan import ExecutionPlan
        from .task_spec import snapshot_identity
        request = BrowserActionRequest.model_validate(request.model_dump())
        run = self._verify(db, request.identity.task_id)
        snapshot = json.loads(run['snapshot'])
        if snapshot.get('mode') != 'browser_task' or snapshot.get('permissions', {}).get('browser') is not True:
            raise PermissionError('Task does not authorize browser execution')
        scope = BrowserTaskScope.model_validate(snapshot.get('browser_scope'))
        registered = ExecutionPlan.model_validate(snapshot.get('execution_plan'))
        planned = next((item for item in registered.steps if item.step_id == request.step_id), None)
        if (planned is None or planned.tool != 'browser.execute'
                or request.origin not in scope.origins or request.action not in scope.actions
                or request.environment != scope.environment):
            raise PermissionError('Browser action is outside the confirmed website/action scope')
        step = db.execute('SELECT state,claim_token FROM execution_steps WHERE run=? AND step_id=?',
                          (run['id'], request.step_id)).fetchone()
        plan = db.execute('SELECT revision FROM execution_plans WHERE run=?', (run['id'],)).fetchone()
        if (request.identity != snapshot_identity(snapshot) or request.identity.owner != self.store.owner
                or request.identity.session_id != run['session'] or request.identity.project_id != run['project']
                or run['state'] != 'running' or step is None or step['state'] != 'running'
                or step['claim_token'] != request.claim_token
                or plan is None or plan['revision'] != request.revision):
            raise PermissionError('Browser action is outside the active task step')
        return request, sha256(request.model_dump_json().encode('utf-8')).hexdigest()

    def authorize_browser_action(self, request, *, confirmed):
        """Native confirmation only. Store digests, never webpage values or passwords."""
        if confirmed is not True:
            raise PermissionError('Browser action requires explicit confirmation')
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            request, binding = self._browser_binding(db, request)
            previous = db.execute('SELECT * FROM browser_action_authorizations WHERE run=? AND binding_sha256=?',
                                  (request.identity.task_id, binding)).fetchone()
            if previous is not None:
                if previous['consumed'] or previous['expires_at'] <= time.time():
                    raise PermissionError('Observe and confirm a fresh action before retrying')
                return previous['id']
            receipt = uuid4().hex
            db.execute('INSERT INTO browser_action_authorizations VALUES(?,?,?,?,?,?,0)',
                       (receipt, request.identity.task_id, request.step_id, binding, now(), time.time()+60))
            return receipt

    def consume_browser_action(self, receipt_id, request):
        """Claim before dispatch. Crash after claiming must never auto-replay a write."""
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            request, binding = self._browser_binding(db, request)
            changed = db.execute('UPDATE browser_action_authorizations SET consumed=1 '
                                 'WHERE id=? AND run=? AND binding_sha256=? AND consumed=0 AND expires_at>?',
                                 (receipt_id, request.identity.task_id, binding, time.time()))
            if changed.rowcount != 1:
                raise PermissionError('Browser action receipt is unavailable, expired or consumed')

    def revoke(self, run_id):
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            self.executions._run(db, run_id)
            db.execute('UPDATE execution_authorizations SET revoked=1 WHERE run=?', (run_id,))
