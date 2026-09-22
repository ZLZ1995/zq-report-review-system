"""AgentKernel: submit/abort/steer/follow_up/recover + event fan-out.

事件规则：先提交存储，再广播给 listener；listener 异常既不影响
持久化也不影响 loop（UI 断开不影响持久化完成）。
"""
import asyncio
import logging
from collections import deque
from datetime import datetime, timezone
from uuid import uuid4

logger = logging.getLogger(__name__)

# S2-01：进程级执行者标识。同一进程内多个 kernel 共享，跨进程必然不同，
# 使 recover() 能区分"别的进程还活着"与"残留任务"。
_PROCESS_EXECUTOR_ID = uuid4().hex

from .cancellation import CancelToken
from .contracts import (
    AUTO_RESUME_POLICIES,
    DEFAULT_RECOVERY_POLICY_BY_RISK,
    OperationAccepted,
)
from .errors import (
    AgentCancelled,
    AgentError,
    AgentInternalError,
    ToolUnknownOutcome,
)
from .events import AgentEvent
from .fakes import OPEN_STATUSES, TOOL_CALL_OPEN_STATUSES
from .loop import run_agent_loop

# repo 生命周期方法已自行持久化的事件，kernel 不再重复落库；
# message_delta 为瞬时事件，不落库（由 message_committed 收束）。
REPO_PERSISTED = frozenset({
    'operation_accepted', 'operation_completed', 'operation_failed',
    'operation_aborted', 'operation_unknown', 'operation_resumed',
})
TRANSIENT = frozenset({'message_delta'})


def _now():
    return datetime.now(timezone.utc).isoformat()


def _sanitize_summary(message):
    """未归类异常的对外摘要：不泄露路径、token、API key、traceback。"""
    text = str(message or '').strip()
    if not text or len(text) > 200 or any(
            token in text.lower()
            for token in ('token', 'bearer', 'password', 'api_key', 'secret',
                          'traceback', ':\\')):
        return ''
    return text


class AgentKernel:
    def __init__(self, *, repo, model, tools=(), max_turns=8,
                 tool_resolver=None, policy=None, approver=None,
                 file_scope=None, context_builder=None,
                 executor_id=None, lease_seconds=15.0,
                 heartbeat_interval=5.0):
        self.repo = repo
        self._model = model
        self.tools = list(tools)
        self.max_turns = max_turns
        self._tool_resolver = tool_resolver
        self._policy = policy
        self._approver = approver
        self._file_scope = file_scope
        self._context_builder = context_builder
        # S2-01 执行 lease：executor 默认进程级标识，可注入以便测试双进程语义
        self.executor_id = executor_id or _PROCESS_EXECUTOR_ID
        self.lease_seconds = lease_seconds
        self.heartbeat_interval = heartbeat_interval
        self._listeners = []
        self._sequence = 0
        self._tasks = {}
        self._cancels = {}
        self._steers = {}
        self._followups = {}

    # ---------------------------------------------------------------- events

    def subscribe(self, listener):
        self._listeners.append(listener)
        return lambda: self._listeners.remove(listener)

    def _emit(self, event_type, *, session_id, lane_id, operation_id=None,
              turn_id=None, tool_call_id=None, payload=None):
        if event_type not in REPO_PERSISTED and event_type not in TRANSIENT:
            # 事件落库失败不得穿透主状态机：operation 终态由生命周期方法
            # 自行保证，旁路审计日志异常只告警（P1-05）。
            try:
                self.repo.record_event(
                    session_id, lane_id, event_type, operation_id=operation_id,
                    turn_id=turn_id, tool_call_id=tool_call_id, payload=payload)
            except Exception:
                logger.warning('事件落库失败已隔离: %s', event_type,
                               exc_info=True)
        self._sequence += 1
        event = AgentEvent(
            event_type=event_type, session_id=session_id, lane_id=lane_id,
            sequence=self._sequence, timestamp=_now(),
            operation_id=operation_id, turn_id=turn_id,
            tool_call_id=tool_call_id, payload=payload or {})
        for listener in list(self._listeners):
            try:
                listener(event)
            except Exception:
                logger.warning('事件 listener 异常已隔离: %s', event_type,
                               exc_info=True)
                continue
        return event

    # ------------------------------------------------------------- operations

    def _ensure_terminal(self, operation, exc):
        """S1-01 终态兜底：begin_operation 之后任何异常路径都必须收束。

        - 取消 → aborted；
        - 已归类 AgentError → failed（保留原 code）；
        - 未归类内部异常 → failed / agent.internal_error，摘要安全化；
        收束本身失败（如库已损坏）只告警，不再穿透。
        """
        try:
            current = self.repo.get_operation(operation.id)
        except Exception:
            logger.exception('终态兜底读取 operation 失败: %s', operation.id)
            return
        if current.status not in OPEN_STATUSES:
            return
        try:
            if isinstance(exc, AgentCancelled):
                self.repo.abort_operation(
                    operation.id, turn_id=current.current_turn_id)
                self._emit('operation_aborted',
                           session_id=operation.session_id,
                           lane_id=operation.lane_id, operation_id=operation.id,
                           payload={'error_code': AgentCancelled.code})
                return
            code = exc.code if isinstance(exc, AgentError) \
                else AgentInternalError.code
            summary = _sanitize_summary(str(exc)) or '内部处理失败'
            self.repo.fail_operation(
                operation.id, code=code, summary=summary,
                turn_id=current.current_turn_id)
            self._emit('operation_failed', session_id=operation.session_id,
                       lane_id=operation.lane_id, operation_id=operation.id,
                       payload={'error_code': code})
        except Exception:
            logger.exception('终态兜底收束失败: %s', operation.id)

    @property
    def model(self):
        """S2-03 对账接线用：当前 ModelPort（可能具备 reconcile/replay）。"""
        return self._model

    async def submit(self, session_id, lane_id, request, *, wait=True):
        if not isinstance(request, dict) or not str(request.get('text', '')).strip():
            from .errors import InvalidRequest
            raise InvalidRequest('用户请求必须包含非空 text')
        tools = self.tools
        snapshot = None
        if self._tool_resolver is not None:
            # Operation accept 时解析资源并固定版本快照（S07 运行时规则）
            tools, snapshot = self._tool_resolver.resolve_for_operation(
                skill_ids=request.get('skill_ids'))
        operation_args = {
            'user_text': request['text'].strip(),
            'request_id': uuid4().hex,
            # S2-01：operation 从创建起就携带执行 lease
            'executor_id': self.executor_id,
            'lease_seconds': self.lease_seconds,
        }
        if request.get('model_id'):
            operation_args['model_id'] = request['model_id']
        file_bindings = tuple(request.get('file_bindings') or ())
        # Validate the complete batch before accepting the operation. This
        # prevents malformed input from leaving a lane permanently busy.
        for binding in file_bindings:
            file_id = str(binding.get('file_id', '')).strip()
            binding_sha256 = str(binding.get('sha256', '')).strip()
            if not file_id or not binding_sha256:
                from .errors import InvalidRequest
                raise InvalidRequest('file binding requires file_id and sha256')
        operation = self.repo.begin_operation(
            session_id, lane_id, **operation_args)
        try:
            for binding in file_bindings:
                # 本轮勾选/上传的文件必须先绑定再进入 loop：ContextBuilder 只读取
                # 当前 operation 的 explicit 绑定，缺绑定即“本轮文件摘要：无”。
                file_id = str(binding.get('file_id', '')).strip()
                sha256 = str(binding.get('sha256', '')).strip()
                if not file_id or not sha256:
                    from .errors import InvalidRequest
                    raise InvalidRequest('文件绑定必须包含 file_id 与 sha256')
                self.repo.bind_file(
                    operation.id, file_id,
                    binding.get('binding_kind') or 'explicit_selection',
                    sha256=sha256, role=binding.get('role'),
                    source_entry_id=binding.get('source_entry_id'))
            if hasattr(self.repo, 'set_file_scope_snapshot'):
                self.repo.set_file_scope_snapshot(
                    operation.id,
                    {'files': [
                        {'file_id': str(binding.get('file_id')),
                         'sha256': str(binding.get('sha256')),
                         'binding_kind': binding.get('binding_kind') or
                         'explicit_selection'}
                        for binding in file_bindings
                    ]})
            if snapshot:
                self.repo.set_resource_snapshot(operation.id, snapshot)
        except Exception as exc:  # noqa: BLE001 - S1-01：begin 后异常必须收束
            self._ensure_terminal(operation, exc)
            return OperationAccepted(
                operation_id=operation.id, session_id=session_id,
                lane_id=lane_id, request_id=operation.request_id)
        accepted = OperationAccepted(
            operation_id=operation.id, session_id=session_id,
            lane_id=lane_id, request_id=operation.request_id)
        self._emit('operation_accepted', session_id=session_id, lane_id=lane_id,
                   operation_id=operation.id,
                   payload={'request_id': operation.request_id})
        await self._drive(operation, tools, wait=wait)
        return accepted

    async def _heartbeat_loop(self, operation_id):
        """S2-01：驱动期间周期刷新 lease；repo 异常只告警不穿透。"""
        while True:
            await asyncio.sleep(self.heartbeat_interval)
            try:
                if not self.repo.heartbeat_operation(
                        operation_id, self.executor_id, self.lease_seconds):
                    return  # operation 已终态，停止心跳
            except Exception:
                logger.warning('lease 心跳失败: %s', operation_id,
                               exc_info=True)
                return

    async def _drive(self, operation, tools, *, wait):
        session_id, lane_id = operation.session_id, operation.lane_id
        cancel = CancelToken()
        self._cancels[operation.id] = cancel
        self._steers[operation.id] = deque()

        async def drive():
            heartbeat = asyncio.ensure_future(
                self._heartbeat_loop(operation.id))
            try:
                await run_agent_loop(
                    repo=self.repo, model=self._model, tools=tools,
                    operation=operation, cancel=cancel,
                    steer_queue=self._steers[operation.id],
                    emit=lambda kind, **kw: self._emit(
                        kind, session_id=session_id, lane_id=lane_id,
                        operation_id=operation.id, **kw),
                    max_turns=self.max_turns,
                    policy=self._policy, approver=self._approver,
                    file_scope=self._file_scope,
                    context_builder=self._context_builder)
            except Exception as exc:  # noqa: BLE001 - S1-01 终态兜底
                self._ensure_terminal(operation, exc)
            finally:
                heartbeat.cancel()
                await asyncio.gather(heartbeat, return_exceptions=True)
                self._steers.pop(operation.id, None)
                self._cancels.pop(operation.id, None)
                await self._drain_followups(session_id, lane_id)

        if wait:
            await drive()
        else:
            task = asyncio.ensure_future(drive())
            self._tasks[operation.id] = task
            task.add_done_callback(
                lambda done: self._on_background_task_done(operation.id, done))
        return operation

    def _on_background_task_done(self, operation_id, task):
        """S1-05：后台 Task 完成后即从注册表清除，并消费异常引用。"""
        self._tasks.pop(operation_id, None)
        if task.cancelled():
            return
        exc = task.exception()
        if exc is not None:
            logger.error('后台 operation 任务异常: %s', exc)

    async def resume(self, operation_id, *, wait=True):
        """恢复中断（unknown）的 operation：必须找到快照中的原版本资源，
        找不到则失败收束（resource.version_changed），不得换版本重跑。"""
        from .errors import ResourceVersionChanged
        operation = self.repo.get_operation(operation_id)
        if operation.status != 'unknown':
            raise ValueError('只有中断（unknown）的 operation 可以恢复')
        if self._tool_resolver is None:
            raise ValueError('未配置资源解析器，无法按原版本恢复')
        snapshot = self.repo.resource_snapshot(operation_id)
        try:
            tools = self._tool_resolver.resolve_pinned(snapshot)
        except ResourceVersionChanged as exc:
            self.repo.fail_operation(
                operation_id, code=exc.code, summary=str(exc), turn_id=None)
            self._emit('operation_failed', session_id=operation.session_id,
                       lane_id=operation.lane_id, operation_id=operation_id,
                       payload={'error_code': exc.code})
            raise
        # S1-02/S2-02：中断时存在 open/unknown ToolCall 的 operation 按
        # Tool Recovery Policy 判定——safe_replay/idempotent_retry 才允许
        # 自动续跑；query_before_retry/manual_reconcile/never_retry 一律
        # 收束为 tool.unknown_outcome，绝不自动再次执行。
        pending = [c for c in self.repo.tool_calls(operation_id)
                   if c.status in TOOL_CALL_OPEN_STATUSES
                   or c.status == 'unknown']
        if pending:
            descriptors = {tool.descriptor.name: tool.descriptor
                           for tool in tools}
            blocking = []
            for call in pending:
                descriptor = descriptors.get(call.tool_name)
                if descriptor is not None:
                    policy = descriptor.effective_recovery_policy
                else:
                    policy = DEFAULT_RECOVERY_POLICY_BY_RISK.get(
                        call.risk_level, 'manual_reconcile')
                if policy not in AUTO_RESUME_POLICIES:
                    blocking.append((call.tool_name, policy))
            if blocking:
                exc = ToolUnknownOutcome(
                    '存在不可判定副作用的工具调用，需人工核对后才能继续')
                self.repo.fail_operation(
                    operation_id, code=exc.code, summary=str(exc), turn_id=None)
                self._emit('operation_failed', session_id=operation.session_id,
                           lane_id=operation.lane_id, operation_id=operation_id,
                           payload={'error_code': exc.code})
                raise exc
        self.repo.resume_operation(operation_id)
        # 恢复即认领 lease：本进程成为新的执行 owner
        self.repo.heartbeat_operation(
            operation_id, self.executor_id, self.lease_seconds)
        operation = self.repo.get_operation(operation_id)
        self._emit('operation_resumed', session_id=operation.session_id,
                   lane_id=operation.lane_id, operation_id=operation_id)
        return await self._drive(operation, tools, wait=wait)

    async def wait(self, operation_id):
        task = self._tasks.get(operation_id)
        if task is not None:
            await task

    async def abort(self, operation_id):
        token = self._cancels.get(operation_id)
        if token is not None:
            token.cancel()
        await self.wait(operation_id)
        return self.repo.get_operation(operation_id)

    def cancel_open(self, operation_ids=None):
        """Thread-safe cancellation signal for a UI thread.

        The kernel owns asyncio Tasks on the worker loop; a foreign thread
        must not call ``asyncio.run(abort())`` against that loop.  Cancellation
        tokens are deliberately synchronous and are polled by model/tool
        boundaries, while the worker loop performs the durable abort.
        """
        wanted = set(operation_ids) if operation_ids is not None else set(self._cancels)
        cancelled = []
        for operation_id in wanted:
            token = self._cancels.get(operation_id)
            if token is not None:
                token.cancel()
                cancelled.append(operation_id)
        return cancelled

    async def steer(self, operation_id, message):
        """向运行中的 operation 注入用户消息，下一 turn 边界生效。"""
        text = str((message or {}).get('text', '')).strip()
        if not text:
            from .errors import InvalidRequest
            raise InvalidRequest('steer 消息必须包含非空 text')
        queue = self._steers.get(operation_id)
        if queue is None or \
                self.repo.get_operation(operation_id).status not in OPEN_STATUSES:
            raise ValueError('operation 已结束，无法 steer')
        queue.append(text)
        return {'queued': True, 'operation_id': operation_id}

    async def follow_up(self, session_id, lane_id, message):
        """lane 忙时排队，当前 operation 终态后自动接续。"""
        text = str((message or {}).get('text', '')).strip()
        if not text:
            from .errors import InvalidRequest
            raise InvalidRequest('follow-up 消息必须包含非空 text')
        busy = any(op.lane_id == lane_id and op.session_id == session_id
                   for op in self.repo.open_operations(session_id))
        if not busy:
            accepted = await self.submit(session_id, lane_id, {'text': text},
                                         wait=False)
            return {'queued': False, 'operation_id': accepted.operation_id}
        queue = self._followups.setdefault((session_id, lane_id), deque())
        queue.append(text)
        return {'queued': True, 'position': len(queue)}

    async def _drain_followups(self, session_id, lane_id):
        queue = self._followups.get((session_id, lane_id))
        if not queue:
            return
        while queue and not any(
                op.lane_id == lane_id and op.session_id == session_id
                for op in self.repo.open_operations(session_id)):
            text = queue.popleft()
            await self.submit(session_id, lane_id, {'text': text}, wait=False)

    # -------------------------------------------------------------- recovery

    async def recover(self, session_id=None):
        """启动恢复：开放 operation 收束为 unknown 并给出用户可见错误。

        S2-01：lease 未过期的 operation 属于仍在执行的进程，recover 不得
        收束（双开客户端不得误杀对方任务）；只处理无 owner / lease 已过期的。
        """
        interrupted = []
        for operation in self.repo.open_operations(session_id):
            if self._lease_alive(operation):
                continue
            self.repo.interrupt_operation(
                operation.id, code='agent.interrupted',
                summary='进程中断，等待对账')
            self._emit('operation_unknown', session_id=operation.session_id,
                       lane_id=operation.lane_id, operation_id=operation.id,
                       payload={'error_code': 'agent.interrupted'})
            self._emit('recovery_required', session_id=operation.session_id,
                       lane_id=operation.lane_id, operation_id=operation.id,
                       payload={'reason': 'agent.interrupted'})
            interrupted.append(operation.id)
        return {'interrupted': interrupted}

    @staticmethod
    def _lease_alive(operation):
        """lease 未过期视为活任务；缺失/损坏时间戳一律按可恢复处理。"""
        expires = getattr(operation, 'lease_expires_at', None)
        if not expires:
            return False
        try:
            return datetime.fromisoformat(expires) > datetime.now(timezone.utc)
        except (TypeError, ValueError):
            return False
