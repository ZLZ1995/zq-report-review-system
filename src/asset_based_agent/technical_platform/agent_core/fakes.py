"""Fake runtime pieces for tests and shadow mode.

FakeModelPort / FakeTool / InMemorySessionRepo 实现与生产相同的契约，
供单元测试、contract tests 和 S13 Shadow Mode 复用。
"""
import json
from datetime import datetime, timezone
from hashlib import sha256
from uuid import uuid4

from .contracts import ModelRequest, ToolDescriptor, ToolResult
from .errors import ModelProtocolError, OperationBusy
from .messages import SCHEMA_VERSION, ConversationEntry

OPEN_STATUSES = frozenset({
    'accepted', 'running', 'waiting_input', 'waiting_approval',
    'deferred', 'suspended', 'aborting',
})

# agent_core 不得 import sessions（依赖方向），此处内联同一集合。
OPERATION_KINDS = frozenset({'consult', 'execution', 'browser', 'query'})

BINDING_KINDS = frozenset({
    'explicit_upload', 'explicit_selection', 'explicit_mention',
    'agent_discovered', 'project_reference', 'historical_reference',
    'generated_artifact'})
EXPLICIT_BINDING_KINDS = frozenset(
    {'explicit_upload', 'explicit_selection', 'explicit_mention'})

FACT_STATUS_TRANSITIONS = {
    'proposed': frozenset({'confirmed', 'rejected'}),
    'confirmed': frozenset({'superseded'}),
    'rejected': frozenset(),
    'superseded': frozenset()}


def _now():
    return datetime.now(timezone.utc).isoformat()


TURN_OPEN_STATUSES = frozenset(
    {'queued', 'model_streaming', 'tool_batch', 'awaiting_continuation'})
TOOL_CALL_OPEN_STATUSES = frozenset({'proposed', 'running'})


class Turn:
    def __init__(self, *, id, operation_id, ordinal, input_context_sha256,
                 model_request_id=''):
        self.id = id
        self.operation_id = operation_id
        self.ordinal = ordinal
        self.status = 'model_streaming'
        self.model_request_id = model_request_id
        self.input_context_sha256 = input_context_sha256
        self.assistant_entry_id = None
        self.started_at = _now()
        self.finished_at = None
        self.error_code = None
        self.usage = {}


class ToolCall:
    def __init__(self, *, id, operation_id, turn_id, tool_name, arguments,
                 arguments_sha256, risk_level, idempotency_key):
        self.id = id
        self.operation_id = operation_id
        self.turn_id = turn_id
        self.tool_name = tool_name
        self.arguments = arguments
        self.arguments_sha256 = arguments_sha256
        self.risk_level = risk_level
        self.authorization_id = None
        self.status = 'proposed'
        self.result_entry_id = None
        self.idempotency_key = idempotency_key
        self.started_at = _now()
        self.finished_at = None
        self.error_code = None


class Operation:
    def __init__(self, *, id, session_id, lane_id, request_id, source_entry_id,
                 kind='consult'):
        self.id = id
        self.session_id = session_id
        self.lane_id = lane_id
        self.kind = kind
        self.status = 'running'
        self.request_id = request_id
        self.source_entry_id = source_entry_id
        self.current_turn_id = None
        self.error_code = None
        self.error_summary = None
        self.resource_snapshot = []
        self.accepted_at = _now()
        self.finished_at = None


class InMemorySessionRepo:
    """契约级内存实现；SQLite 实现（S03）必须通过同一组 contract tests。"""

    def __init__(self):
        self._sessions = {}
        self._lanes = {}
        self._entries = []
        self._operations = {}
        self._turns = {}
        self._tool_calls = {}
        self._events = []
        self._sequence = 0
        self._facts = {}
        self._bindings = {}
        self._compactions = []

    # ---------------------------------------------------------- structure

    def create_session(self, session_id, *, project_id, owner_id, title,
                       permission_mode='full'):
        self._sessions[session_id] = {
            'id': session_id, 'project_id': project_id, 'owner_id': owner_id,
            'title': title, 'permission_mode': permission_mode}
        self.create_lane(session_id, 'main', name='main')

    def session_permission_mode(self, session_id):
        return self._sessions[session_id]['permission_mode']

    def session_project_id(self, session_id):
        return self._sessions[session_id]['project_id']

    def list_sessions(self):
        return [{'id': s['id'], 'project_id': s['project_id'],
                 'title': s['title'], 'permission_mode': s['permission_mode']}
                for s in self._sessions.values()]

    # ------------------------------------------------- facts / bindings

    def propose_fact(self, project_id, scope, fact_key, value, *,
                     source_entry_id=None, confidence=1.0):
        from .text_safety import contains_secret
        canonical = json.dumps(value, ensure_ascii=False)
        if contains_secret(canonical) or contains_secret(fact_key):
            raise ValueError('禁止把密码、Token 或密钥写入项目事实')
        fact_id = uuid4().hex
        self._facts[fact_id] = {
            'id': fact_id, 'project_id': project_id, 'scope': scope,
            'fact_key': fact_key, 'value': value,
            'source_entry_id': source_entry_id, 'confidence': confidence,
            'status': 'proposed', 'created_at': _now(), 'updated_at': _now()}
        return fact_id

    def set_fact_status(self, fact_id, status):
        fact = self._facts[fact_id]
        if status not in FACT_STATUS_TRANSITIONS.get(fact['status'], frozenset()):
            raise ValueError(f"非法事实状态迁移: {fact['status']} → {status}")
        fact['status'] = status
        fact['updated_at'] = _now()

    def facts(self, project_id, *, status='confirmed', scope=None):
        return [dict(f) for f in self._facts.values()
                if f['project_id'] == project_id and f['status'] == status
                and (scope is None or f['scope'] == scope)]

    def bind_file(self, operation_id, file_id, binding_kind, *, sha256,
                  role=None, source_entry_id=None):
        if binding_kind not in BINDING_KINDS:
            raise ValueError(f'非法文件绑定类型: {binding_kind}')
        if operation_id not in self._operations:
            raise KeyError(f'未知 operation: {operation_id}')
        self._bindings[(operation_id, file_id, binding_kind)] = {
            'operation_id': operation_id, 'file_id': file_id,
            'binding_kind': binding_kind, 'source_entry_id': source_entry_id,
            'role': role, 'sha256': sha256}

    def set_file_scope_snapshot(self, operation_id, snapshot):
        self._operations[operation_id].file_scope_snapshot = dict(snapshot or {})

    def operation_files(self, operation_id, kinds=None):
        wanted = EXPLICIT_BINDING_KINDS if kinds is None else frozenset(kinds)
        return [dict(b) for key, b in self._bindings.items()
                if key[0] == operation_id and b['binding_kind'] in wanted]

    def legacy_project_files(self, project_id):
        return []  # 内存仓储无 legacy files 表

    # --------------------------------------------------------- compaction

    def save_compaction(self, session_id, lane_id, *, source_start_entry_id,
                        source_end_entry_id, source_sha256, summary_entry_id):
        record = {'id': uuid4().hex, 'session_id': session_id,
                  'lane_id': lane_id,
                  'source_start_entry_id': source_start_entry_id,
                  'source_end_entry_id': source_end_entry_id,
                  'source_sha256': source_sha256,
                  'summary_entry_id': summary_entry_id,
                  'created_at': _now()}
        self._compactions.append(record)
        return record['id']

    def latest_compaction(self, session_id, lane_id):
        matches = [c for c in self._compactions
                   if c['session_id'] == session_id and c['lane_id'] == lane_id]
        return dict(matches[-1]) if matches else None

    def set_permission_mode(self, session_id, mode):
        # 与 policies.PERMISSION_MODES 同源内联（agent_core 不得 import policies）
        if mode not in {'request', 'assisted', 'full'}:
            raise ValueError(f'非法权限模式: {mode}')
        self._sessions[session_id]['permission_mode'] = mode

    def create_lane(self, session_id, lane_id, *, name, parent_lane_id=None,
                    anchor_entry_id=None):
        if session_id not in self._sessions:
            raise KeyError(f'未知会话: {session_id}')
        if anchor_entry_id is not None and not any(
                e.id == anchor_entry_id and e.session_id == session_id
                for e in self._entries):
            raise KeyError(f'未知锚点 entry: {anchor_entry_id}')
        self._lanes[(session_id, lane_id)] = {
            'id': lane_id, 'session_id': session_id, 'name': name,
            'parent_lane_id': parent_lane_id, 'anchor_entry_id': anchor_entry_id,
            'leaf_entry_id': anchor_entry_id}

    def delete_lane(self, session_id, lane_id):
        if lane_id == 'main':
            raise ValueError('main lane 不可删除')
        has_open = False
        has_history = False
        for operation in self._operations.values():
            if operation.lane_id == lane_id and operation.session_id == session_id:
                if operation.status in OPEN_STATUSES:
                    has_open = True
                else:
                    has_history = True
        if has_open:
            raise OperationBusy('本会话分支正在处理上一条消息')
        if has_history:
            raise ValueError('lane 已有操作历史，审计记录不可删除')
        own_entry_ids = {e.id for e in self._entries
                         if e.session_id == session_id and e.lane_id == lane_id}
        for key, lane in self._lanes.items():
            if key == (session_id, lane_id):
                continue
            if lane['parent_lane_id'] == lane_id \
                    or lane['anchor_entry_id'] in own_entry_ids:
                raise ValueError('存在子分支，无法删除')
        self._entries = [e for e in self._entries
                         if not (e.session_id == session_id
                                 and e.lane_id == lane_id)]
        del self._lanes[(session_id, lane_id)]

    # --------------------------------------------------------------- tree

    def lane_history(self, session_id, lane_id, *, limit=None):
        cap = 10000 if limit is None else limit
        lane = self._lanes[(session_id, lane_id)]
        by_id = {e.id: e for e in self._entries}
        chain = []
        current = lane['leaf_entry_id']
        while current is not None and len(chain) < cap:
            entry = by_id.get(current)
            if entry is None:
                break
            chain.append(entry)
            current = entry.parent_id
        chain.reverse()
        return chain

    def tree(self, session_id):
        lanes = []
        for (lane_session, lane_id), lane in self._lanes.items():
            if lane_session != session_id:
                continue
            lanes.append({
                'id': lane_id, 'name': lane['name'],
                'parent_lane_id': lane['parent_lane_id'],
                'anchor_entry_id': lane['anchor_entry_id'],
                'leaf_entry_id': lane['leaf_entry_id'],
                'state': 'idle',
                'entry_count': len(self.entries(session_id, lane_id))})
        return {'session_id': session_id, 'lanes': lanes}

    # ------------------------------------------------------------- entries

    def append_entry(self, session_id, lane_id, entry_type, payload, *,
                     operation_id=None, turn_id=None):
        lane = self._lanes[(session_id, lane_id)]
        self._sequence += 1
        entry = ConversationEntry(
            id=uuid4().hex, session_id=session_id, lane_id=lane_id,
            parent_id=lane['leaf_entry_id'], sequence=self._sequence,
            entry_type=entry_type, payload=dict(payload),
            operation_id=operation_id, turn_id=turn_id,
            schema_version=SCHEMA_VERSION, created_at=_now())
        lane['leaf_entry_id'] = entry.id
        self._entries.append(entry)
        return entry

    def entries(self, session_id, lane_id):
        return [e for e in self._entries
                if e.session_id == session_id and e.lane_id == lane_id]

    # ---------------------------------------------------------- operations

    def begin_operation(self, session_id, lane_id, *, user_text, request_id,
                        kind='consult'):
        if kind not in OPERATION_KINDS:
            raise ValueError(f'非法 operation 类型: {kind}')
        if (session_id, lane_id) not in self._lanes:
            raise KeyError(f'未知 lane: {session_id}/{lane_id}')
        if self._sessions[session_id]['permission_mode'] == 'readonly':
            raise ValueError('只读历史会话禁止写入')
        for operation in self._operations.values():
            if operation.lane_id == lane_id and operation.session_id == session_id \
                    and operation.status in OPEN_STATUSES:
                raise OperationBusy('本会话分支正在处理上一条消息')
        source = self.append_entry(session_id, lane_id, 'user_message',
                                   {'text': user_text})
        operation = Operation(id=uuid4().hex, session_id=session_id,
                              lane_id=lane_id, request_id=request_id,
                              source_entry_id=source.id, kind=kind)
        self._operations[operation.id] = operation
        self.record_event(session_id, lane_id, 'operation_accepted',
                          operation_id=operation.id,
                          payload={'request_id': request_id})
        return operation

    def get_operation(self, operation_id):
        return self._operations[operation_id]

    def open_operations(self, session_id=None):
        return [op for op in self._operations.values()
                if op.status in OPEN_STATUSES
                and (session_id is None or op.session_id == session_id)]

    def complete_operation(self, operation_id, *, assistant_entry_id, turn_id):
        operation = self._operations[operation_id]
        operation.status = 'completed'
        operation.current_turn_id = turn_id
        operation.finished_at = _now()
        self.record_event(operation.session_id, operation.lane_id,
                          'operation_completed', operation_id=operation_id,
                          turn_id=turn_id)

    def fail_operation(self, operation_id, *, code, summary, turn_id):
        operation = self._operations[operation_id]
        operation.status = 'failed'
        operation.error_code = code
        operation.error_summary = summary
        operation.current_turn_id = turn_id
        operation.finished_at = _now()
        self.append_entry(
            operation.session_id, operation.lane_id, 'error_message',
            {'text': f'本轮处理未完成（{code}）。', 'error_code': code},
            operation_id=operation_id, turn_id=turn_id)
        self.record_event(operation.session_id, operation.lane_id,
                          'operation_failed', operation_id=operation_id,
                          turn_id=turn_id, payload={'error_code': code})

    def abort_operation(self, operation_id, *, turn_id):
        operation = self._operations[operation_id]
        operation.status = 'aborted'
        operation.error_code = 'agent.cancelled'
        operation.current_turn_id = turn_id
        operation.finished_at = _now()
        self.append_entry(
            operation.session_id, operation.lane_id, 'error_message',
            {'text': '本轮已取消。', 'error_code': 'agent.cancelled'},
            operation_id=operation_id, turn_id=turn_id)
        self.record_event(operation.session_id, operation.lane_id,
                          'operation_aborted', operation_id=operation_id,
                          turn_id=turn_id,
                          payload={'error_code': 'agent.cancelled'})

    def interrupt_operation(self, operation_id, *, code, summary):
        """崩溃恢复：operation/turn/tool call 全部收束为 unknown。"""
        operation = self._operations[operation_id]
        operation.status = 'unknown'
        operation.error_code = code
        operation.error_summary = summary
        operation.finished_at = _now()
        for turn in self._turns.values():
            if turn.operation_id == operation_id \
                    and turn.status in TURN_OPEN_STATUSES:
                turn.status = 'unknown'
                turn.error_code = code
                turn.finished_at = _now()
        for call in self._tool_calls.values():
            if call.operation_id == operation_id \
                    and call.status in TOOL_CALL_OPEN_STATUSES:
                call.status = 'unknown'
                call.error_code = code
                call.finished_at = _now()
        self.append_entry(
            operation.session_id, operation.lane_id, 'error_message',
            {'text': f'本轮被中断（{code}），等待对账。', 'error_code': code},
            operation_id=operation_id)
        self.record_event(operation.session_id, operation.lane_id,
                          'operation_unknown', operation_id=operation_id,
                          payload={'error_code': code})

    # ------------------------------------------------------- snapshots

    def set_resource_snapshot(self, operation_id, resources):
        operation = self._operations[operation_id]
        operation.resource_snapshot = [dict(entry) for entry in resources]

    def resource_snapshot(self, operation_id):
        operation = self._operations[operation_id]
        return [dict(entry) for entry in operation.resource_snapshot]

    def resume_operation(self, operation_id):
        """按原资源快照恢复中断的 operation：unknown → running。"""
        operation = self._operations[operation_id]
        if operation.status != 'unknown':
            raise ValueError('只有中断（unknown）的 operation 可以恢复')
        operation.status = 'running'
        operation.error_code = None
        operation.error_summary = None
        operation.finished_at = None
        self.record_event(operation.session_id, operation.lane_id,
                          'operation_resumed', operation_id=operation_id)

    # --------------------------------------------------------------- turns

    def begin_turn(self, operation_id, ordinal, *, input_context_sha256,
                   model_request_id=''):
        turn = Turn(id=uuid4().hex, operation_id=operation_id,
                    ordinal=ordinal,
                    input_context_sha256=input_context_sha256,
                    model_request_id=model_request_id)
        self._turns[turn.id] = turn
        return turn.id

    def finish_turn(self, turn_id, status, *, assistant_entry_id=None,
                    error_code=None, usage=None):
        turn = self._turns[turn_id]
        turn.status = status
        turn.assistant_entry_id = assistant_entry_id
        turn.error_code = error_code
        if usage is not None:
            turn.usage = dict(usage)
        turn.finished_at = _now()

    def turns(self, operation_id):
        return sorted(
            (t for t in self._turns.values() if t.operation_id == operation_id),
            key=lambda t: t.ordinal)

    # ----------------------------------------------------------- tool calls

    def begin_tool_call(self, operation_id, turn_id, *, name, arguments,
                        risk, idempotency_key):
        for call in self._tool_calls.values():
            if call.idempotency_key == idempotency_key:
                raise ValueError(f'idempotency_key 重复: {idempotency_key}')
        canonical = json.dumps(arguments, ensure_ascii=False, sort_keys=True)
        call = ToolCall(
            id=uuid4().hex, operation_id=operation_id, turn_id=turn_id,
            tool_name=name, arguments=dict(arguments),
            arguments_sha256=sha256(canonical.encode('utf-8')).hexdigest(),
            risk_level=risk, idempotency_key=idempotency_key)
        self._tool_calls[call.id] = call
        return call.id

    def set_tool_call_authorization(self, call_id, authorization_id):
        self._tool_calls[call_id].authorization_id = authorization_id

    def finish_tool_call(self, call_id, status, *, result_entry_id=None,
                         error_code=None):
        call = self._tool_calls[call_id]
        call.status = status
        call.result_entry_id = result_entry_id
        call.error_code = error_code
        call.finished_at = _now()

    def tool_calls(self, operation_id):
        return [c for c in self._tool_calls.values()
                if c.operation_id == operation_id]

    # --------------------------------------------------------------- events

    def record_event(self, session_id, lane_id, event_type, *,
                     operation_id=None, turn_id=None, tool_call_id=None,
                     payload=None):
        self._events.append({
            'sequence': len(self._events) + 1, 'session_id': session_id,
            'lane_id': lane_id, 'operation_id': operation_id,
            'turn_id': turn_id, 'tool_call_id': tool_call_id,
            'event_type': event_type, 'payload': dict(payload or {}),
            'created_at': _now()})

    def persisted_events(self, session_id):
        return [e for e in self._events if e['session_id'] == session_id]

    # -------------------------------------------------------------- model

    def build_model_request(self, operation):
        history = tuple(
            {'role': e.entry_type, 'payload': e.payload}
            for e in self.entries(operation.session_id, operation.lane_id))
        return ModelRequest(model_id='', messages=history,
                            request_id=operation.request_id)


class FakeModelPort:
    """按脚本逐 turn 回放 ModelEvent；脚本项为异常实例时抛出该异常。"""

    def __init__(self, scripts):
        self._scripts = list(scripts)
        self._factory = None
        self.requests = []

    @classmethod
    def from_stream_factory(cls, factory):
        port = cls([])
        port._factory = factory
        return port

    async def stream(self, request, cancel):
        self.requests.append(request)
        if self._factory is not None:
            produced = self._factory(request, cancel)
            if hasattr(produced, '__aiter__'):
                async for event in produced:
                    yield event
            else:
                for event in produced:
                    yield event
            return
        if not self._scripts:
            raise ModelProtocolError('fake model 脚本已耗尽')
        script = self._scripts.pop(0)
        if isinstance(script, BaseException):
            raise script
        for item in script:
            if isinstance(item, BaseException):
                raise item
            yield item


class FakeTool:
    def __init__(self, name, *, handler, input_schema=None,
                 description='fake tool', risk='local_readonly'):
        self.descriptor = ToolDescriptor(
            name=name, description=description,
            input_schema=input_schema or {}, risk=risk)
        self._handler = handler
        self.calls = []

    async def execute(self, context, arguments, cancel):
        self.calls.append(dict(arguments))
        return ToolResult(status='succeeded',
                          result=self._handler(arguments),
                          content='ok')
