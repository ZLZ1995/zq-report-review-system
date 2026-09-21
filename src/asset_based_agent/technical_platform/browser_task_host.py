"""GUI-thread lifecycle bridge; model completion alone is never success."""
import json
import sqlite3
from threading import Event

from PySide6.QtCore import QCoreApplication, QObject, QThread, Signal, Slot

from .browser_task_spec import BrowserTaskScope
from .conversation_state import ConversationState
from .event_store import ExecutionStore
from .execution_plan import ExecutionPlan
from .permissions import PermissionService
from .store import now


class BrowserTaskHost(QObject):
    progress = Signal(str)
    output = Signal(object)
    completed = Signal(object)
    failed = Signal(str)
    finished = Signal()

    def __init__(self, store, run_id, parent=None, *, runtime_factory, verify_completion=None):
        super().__init__(parent)
        self.store, self.run_id = store, run_id
        self.cancel = Event()
        self.runtime_factory = runtime_factory
        self.verify_completion = verify_completion
        self.runtime = None
        self.plan = None
        self.claim_token = None
        self._running = False
        self._started = False
        self._settling = False

    def isRunning(self):
        return self._running

    def start(self):
        if self._started:
            return
        app = QCoreApplication.instance()
        if app is None or QThread.currentThread() != app.thread():
            raise RuntimeError('Browser task must start on the GUI thread')
        self._started = True
        claimed = False
        try:
            PermissionService(self.store).verify(self.run_id)
            snapshot = json.loads(self.store.run(self.run_id)['snapshot'])
            if snapshot.get('mode') != 'browser_task':
                raise ValueError('Not a browser task')
            BrowserTaskScope.model_validate(snapshot.get('browser_scope'))
            self.plan = ExecutionPlan.model_validate(snapshot.get('execution_plan'))
            if len(self.plan.steps) != 1 or self.plan.steps[0].tool != 'browser.execute':
                raise ValueError('Browser host requires one browser step')
            self.store.claim_run(self.run_id)
            claimed = True
            executions = ExecutionStore(self.store)
            executions.register(self.plan)
            self.claim_token = executions.claim(self.run_id, self.plan.steps[0].step_id)
            self._running = True
            if self.cancel.is_set():
                self._done('cancelled', {})
                return
            self.runtime = self.runtime_factory(self)
            self.runtime.progress.connect(self.progress.emit)
            self.runtime.finished.connect(self._done)
            self.runtime.start()
        except Exception:  # noqa: BLE001 -- native runtime boundary; never expose secrets
            # No exception text: network/page errors may contain credentials.
            if self.claim_token and self._running:
                self._done('unknown', {})
            else:
                if claimed:
                    self.store.transition(self.run_id, 'failed', '浏览器任务初始化失败')
                self._running = False
                self.failed.emit('浏览器任务未启动，请核对任务授权和状态。')
                self.finished.emit()

    @Slot(str, object)
    def _done(self, status, detail):
        if not self._running or self._settling:
            return
        self._settling = True
        verified = False
        receipt = None
        try:
            if status == 'needs_verification' and not self.cancel.is_set():
                PermissionService(self.store).verify(self.run_id)
                if self.verify_completion is not None:
                    verdict = self.verify_completion(detail)
                    if isinstance(verdict, dict):
                        from .browser_completion import validate_readonly_receipt
                        snapshot = json.loads(self.store.run(self.run_id)['snapshot'])
                        if verdict.get('method') == 'user_confirmed_download':
                            from .browser_download_artifacts import (
                                DownloadArtifacts,
                                check_download_identity,
                            )
                            from .browser_download_completion import (
                                validate_download_receipt,
                            )
                            receipt = validate_download_receipt(verdict, snapshot, detail)
                            files = []
                            for item in DownloadArtifacts(self.store).list(self.run_id):
                                check_download_identity(item)
                                files.append({key: item[key] for key in
                                              ('id', 'name', 'size', 'sha256', 'file_identity')}
                                             | {'origin': item['provenance']['origin']})
                            if files != receipt['files']:
                                raise ValueError('Download receipt no longer matches local delivery')
                        else:
                            receipt = validate_readonly_receipt(verdict, snapshot, detail)
                        verified = True
                    # A bare boolean cannot bind a result to a task, website,
                    # object or evidence. Only a validated receipt may succeed.
            # Native verification can run a modal event loop: recheck afterwards.
            if self.cancel.is_set():
                status, verified = 'cancelled', False
            else:
                PermissionService(self.store).verify(self.run_id)
        except Exception:  # noqa: BLE001 -- untrusted verifier failures must fail closed
            status, verified = 'unknown', False
        state = 'succeeded' if verified else 'cancelled' if status == 'cancelled' else 'failed'
        result = {'kind': 'browser', 'verified': verified, 'status': status}
        if verified and receipt is not None:
            result['verification'] = receipt
        if status in {'needs_input', 'needs_verification'} and isinstance(detail, dict):
            # Only bounded user-facing proposal fields; never transport errors,
            # full observations, credential values or arbitrary tool metadata.
            for key in ('summary', 'evidence'):
                value = detail.get(key)
                if isinstance(value, str) and len(value) <= 2000:
                    result[key] = value
        try:
            self._persist(state, result)
        except (sqlite3.Error, ValueError, PermissionError, OSError):
            self.failed.emit('浏览器任务结果未能安全保存；请核对状态，不要重复提交。')
        else:
            self.completed.emit(result)
        finally:
            self._running = False
            self.finished.emit()

    def _persist(self, state, result):
        executions = ExecutionStore(self.store)
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            run = executions._run(db, self.run_id)
            step = db.execute('SELECT * FROM execution_steps WHERE run=?',
                              (self.run_id,)).fetchone()
            if (run['state'] != 'running' or step is None or step['state'] != 'running'
                    or not self.claim_token or step['claim_token'] != self.claim_token):
                raise PermissionError('Task claim changed')
            if state == 'succeeded':
                PermissionService(self.store)._verify(db, self.run_id)
            if result['status'] == 'needs_input' and result.get('summary', '').strip():
                self._handoff_question(db, run, result)
            encoded = json.dumps(result, ensure_ascii=False)
            step_state = 'unknown' if result['status'] == 'unknown' else state
            db.execute('UPDATE execution_steps SET state=?,checkpoint_json=?,updated=? '
                       'WHERE run=? AND step_id=?',
                       (step_state, encoded, now(), self.run_id, step['step_id']))
            executions._event(db, self.run_id, step['step_id'], step_state,
                              'browser-terminal:' + self.claim_token)
            if state == 'succeeded':
                db.execute('INSERT INTO events(run,state,detail,created) VALUES(?,?,?,?)',
                           (self.run_id, 'validating', '只读查询结果经用户确认'
                            if result.get('verification', {}).get('method') == 'user_confirmed_readonly'
                            else '浏览器结果独立验证通过', now()))
            db.execute('UPDATE runs SET state=?,result=? WHERE id=?', (state, encoded, self.run_id))
            db.execute('INSERT INTO events(run,state,detail,created) VALUES(?,?,?,?)',
                       (self.run_id, state, '浏览器任务结束：' + result['status'], now()))

    def _handoff_question(self, db, run, result):
        from uuid import uuid4

        from ..agent_contracts import UnderstandingRequest
        snapshot = json.loads(run['snapshot'])
        binding = snapshot.get('conversation_handoff')
        if not isinstance(binding, dict):
            return  # Historical/native tasks without a conversation must not invent one.
        try:
            request = UnderstandingRequest.model_validate(binding.get('request'))
            if (request.request_id != snapshot['request_id']
                    or request.prompt != snapshot['user_request']
                    or request.model_id != snapshot['model']):
                raise ValueError('Conversation request changed')
            context = [item.model_dump() for item in request.context] + [
                {'id': request.message_id, 'role': 'user', 'text': request.prompt}]
            # Validate the NEXT exchange without truncating any user restriction.
            UnderstandingRequest.model_validate({**request.model_dump(),
                'message_id': uuid4().hex, 'prompt': '请补充本轮要求',
                'context': context + [{'id': uuid4().hex, 'role': 'assistant', 'text': result['summary']}]})
            accepted = ConversationState(self.store).execution_question(
                db, run['session'], task_id=binding.get('task_id'),
                expected_revision=binding.get('revision'), text=result['summary'], context=context)
            result['clarification'] = 'pending' if accepted else 'superseded'
        except ValueError:
            result['clarification'] = 'context_limit'
            result['summary'] += '\n追问上下文无法安全续接；请新建会话并完整描述目标和限制。'
