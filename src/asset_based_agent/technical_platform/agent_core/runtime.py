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

from .cancellation import CancelToken
from .contracts import OperationAccepted
from .events import AgentEvent
from .fakes import OPEN_STATUSES
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


class AgentKernel:
    def __init__(self, *, repo, model, tools=(), max_turns=8,
                 tool_resolver=None, policy=None, approver=None,
                 file_scope=None, context_builder=None):
        self.repo = repo
        self._model = model
        self.tools = list(tools)
        self.max_turns = max_turns
        self._tool_resolver = tool_resolver
        self._policy = policy
        self._approver = approver
        self._file_scope = file_scope
        self._context_builder = context_builder
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
            self.repo.record_event(
                session_id, lane_id, event_type, operation_id=operation_id,
                turn_id=turn_id, tool_call_id=tool_call_id, payload=payload)
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
        operation = self.repo.begin_operation(
            session_id, lane_id, user_text=request['text'].strip(),
            request_id=uuid4().hex)
        if snapshot:
            self.repo.set_resource_snapshot(operation.id, snapshot)
        accepted = OperationAccepted(
            operation_id=operation.id, session_id=session_id,
            lane_id=lane_id, request_id=operation.request_id)
        self._emit('operation_accepted', session_id=session_id, lane_id=lane_id,
                   operation_id=operation.id,
                   payload={'request_id': operation.request_id})
        await self._drive(operation, tools, wait=wait)
        return accepted

    async def _drive(self, operation, tools, *, wait):
        session_id, lane_id = operation.session_id, operation.lane_id
        cancel = CancelToken()
        self._cancels[operation.id] = cancel
        self._steers[operation.id] = deque()

        async def drive():
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
            finally:
                self._steers.pop(operation.id, None)
                self._cancels.pop(operation.id, None)
                await self._drain_followups(session_id, lane_id)

        if wait:
            await drive()
        else:
            self._tasks[operation.id] = asyncio.ensure_future(drive())
        return operation

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
        self.repo.resume_operation(operation_id)
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
        """启动恢复：开放 operation 收束为 unknown 并给出用户可见错误。"""
        interrupted = []
        for operation in self.repo.open_operations(session_id):
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
