"""S15 接线子集：AgentGateway——feature flags 驱动的逐类新旧路由。

- 任何 flag 关闭的类别，对应工具**不提供给模型**（能力级隔离，不靠提示词）；
- 会话镜像进新 repo（同一 sqlite 库，v13 表），旧 permission mode
  request/risk/full 映射到新 request/assisted/full；
- 每次 submit 重新装配工具并同步权限模式——flag/模式切换立即生效；
- 浏览器无真实后端时用 NullBrowserBackend（工具可见但执行安全失败），
  真实 QWebEngine 后端由 app.py 注入；
- 旧路径完全不动：flags 全关时 new_path_available 为 False，app.py 走原链路。
"""
from __future__ import annotations

import asyncio
import inspect
import logging

logger = logging.getLogger(__name__)

from .agent_core.context_builder import ContextBuilder
from .agent_core.runtime import AgentKernel
from .business_tools import business_tools
from .business_tools.service import BusinessRunService
from .flags import FEATURE_FLAG_ORDER
from .policies.engine import RuleBasedPolicyEngine
from .policies.file_scope import project_file_scope
from .sessions.sqlite_repository import SQLiteSessionRepo
from .tools.assembly import CompositeToolResolver
from .tools.browser_tools import BrowserToolError, build_browser_tools

MODE_MAP = {'request': 'request', 'risk': 'assisted', 'full': 'full'}


def mark_operations_unknown(repo, operation_ids, *, code, summary) -> int:
    """S6-02 关闭超时兜底：把仍开放的 operation 持久化为 unknown 检查点。

    客户端关闭等不到 worker 安全收束时调用——绝不能只发取消信号就走，
    必须在库中留下 durable 的 unknown 标记，等待重启后对账恢复。
    单个 operation 标记失败不拖垮整批；返回成功标记的数量。
    """
    marked = 0
    for operation_id in tuple(operation_ids):
        try:
            repo.interrupt_operation(operation_id, code=code, summary=summary)
            marked += 1
        except Exception:  # 关闭兜底路径不得再抛错
            logger.warning('关闭检查点写入失败: %s', operation_id, exc_info=True)
    return marked

_SKILL_CATEGORIES = frozenset({
    'single_readonly_skill', 'local_generate_skill', 'report_review',
    'multi_skill'})

_BUSINESS_TOOL_CATEGORY = {
    'inspect_project_files': 'file_readonly_analysis',
    'analyze_file_roles': 'file_readonly_analysis',
    'read_project_file': 'file_readonly_analysis',
    'list_final_artifacts': 'file_readonly_analysis',
    'annotate_reviewed_files': 'review_annotation_copy',
}

_SKILL_TOOL_NAMES = frozenset({
    'execute_skill_plan', 'query_business_run', 'cancel_business_run'})

_BROWSER_READONLY_TOOLS = frozenset({
    'browser_open', 'browser_observe', 'browser_download'})


class NullBrowserBackend:
    """真实后端未接线时的安全占位：任何操作都失败，不产生副作用。"""

    def __getattr__(self, name):
        if name.startswith('_'):
            raise AttributeError(name)

        def _unavailable(*_args):
            raise BrowserToolError('浏览器后端未接线（灰度期由 app 注入）')
        return _unavailable


class AgentGateway:
    def __init__(self, store, session_id, *, flags, model_port_factory,
                 model_id='', permission_mode_getter, provider_factory=None,
                 browser_backend=None, approver=None,
                 force_all_tools: bool = False, tool_registry=None) -> None:
        self._store = store
        self._session_id = session_id
        self._model_id = model_id
        self._flags = flags
        self._model_port_factory = model_port_factory
        self._mode_getter = permission_mode_getter
        self._provider_factory = provider_factory
        self._browser_backend = browser_backend
        self._approver = approver
        self._force_all_tools = force_all_tools
        self._tool_registry = tool_registry
        self.repo = SQLiteSessionRepo(store.path, store.owner)
        self._kernel = None
        self._open_operations = set()

    # ------------------------------------------------------------ 开关

    @property
    def new_path_available(self) -> bool:
        return self._force_all_tools or any(self._flags.enabled(category)
                   for category in FEATURE_FLAG_ORDER)

    def _enabled(self, category) -> bool:
        return self._force_all_tools or self._flags.enabled(category)

    def active_tools(self):
        """按当前 flags 装配工具目录；全关 → 空（app 走旧路径）。"""
        if not self.new_path_available:
            return ()
        tools = []
        if self._tool_registry is not None and any(
                self._enabled(category) for category in _SKILL_CATEGORIES):
            tools.extend(self._tool_registry.resolve_for_operation()[0])
        service = BusinessRunService(self._store, self._session_id,
                                     provider_factory=self._provider_factory)
        tools.extend(self._active_business_tools(service))
        if self._enabled('browser_readonly') \
                or self._enabled('browser_write_upload'):
            backend = self._browser_backend or NullBrowserBackend()
            write = self._enabled('browser_write_upload')
            for tool in build_browser_tools(self._session_id, backend):
                if tool.descriptor.name in _BROWSER_READONLY_TOOLS or write:
                    tools.append(tool)
        return tuple(tools)

    def _active_business_tools(self, service):
        """Apply one identical flag policy to every business-tool catalog."""
        skill_enabled = any(self._enabled(c) for c in _SKILL_CATEGORIES)
        active = []
        for tool in business_tools(service):
            category = _BUSINESS_TOOL_CATEGORY.get(tool.descriptor.name)
            if category is not None and self._enabled(category) or (category is None and skill_enabled
                  and tool.descriptor.name in _SKILL_TOOL_NAMES):
                active.append(tool)
        return active

    def _build_kernel(self):
        """Build one kernel with the same resolver/catalog used at accept time."""
        self._mirror_session()
        service = BusinessRunService(
            self._store, self._session_id,
            provider_factory=self._provider_factory)
        business = self._active_business_tools(service)
        browser = ()
        if self._enabled('browser_readonly') or self._enabled('browser_write_upload'):
            backend = self._browser_backend or NullBrowserBackend()
            write = self._enabled('browser_write_upload')
            browser = tuple(tool for tool in build_browser_tools(
                self._session_id, backend)
                if tool.descriptor.name in _BROWSER_READONLY_TOOLS or write)
        registry = self._tool_registry if any(
            self._enabled(category) for category in _SKILL_CATEGORIES) else None
        resolver = CompositeToolResolver(
            tool_registry=registry,
            browser=browser, extra=business)
        project_id = self.repo.session_project_id(self._session_id)
        project_root = self._store.path.parent
        attachment_root = project_root / 'attachments' / project_id
        scope = project_file_scope(project_root, extra_roots=(attachment_root,))
        tools, _snapshot = resolver.resolve_for_operation()
        return AgentKernel(
            repo=self.repo, model=self._model_port_factory(), tools=tools,
            tool_resolver=resolver, file_scope=scope,
            policy=RuleBasedPolicyEngine(), approver=self._approver,
            context_builder=ContextBuilder())

    # ------------------------------------------------------------ 会话

    def _mirror_session(self):
        mode = MODE_MAP.get(self._mode_getter(), 'request')
        existing = {s['id'] for s in self.repo.list_sessions()}
        if self._session_id not in existing:
            session = self._store.session(self._session_id)
            self.repo.create_session(
                self._session_id, project_id=session['project'],
                owner_id=self._store.owner, title=str(self._session_id),
                permission_mode=mode)
        else:
            self.repo.set_permission_mode(self._session_id, mode)
        # Legacy Qt messages lived outside the Agent tree. Mirror them once so
        # the new ContextBuilder can answer follow-up questions in old
        # sessions; the marker makes the migration idempotent and does not
        # duplicate new Agent entries created later.
        legacy_rows = self._store.messages(self._session_id)
        current = self.repo.entries(self._session_id, 'main')
        mirrored = {
            str(entry.payload.get('_legacy_message_id'))
            for entry in current if entry.payload.get('_legacy_message_id')
        }
        role_map = {'user': 'user_message', 'assistant': 'assistant_message',
                    'event': 'event'}
        for row in legacy_rows:
            legacy_id = str(row.get('id'))
            entry_type = role_map.get(row.get('role'))
            if not entry_type or legacy_id in mirrored:
                continue
            self.repo.append_entry(
                self._session_id, 'main', entry_type,
                {'text': str(row.get('text', '')),
                 '_legacy_message_id': legacy_id},
            )
            mirrored.add(legacy_id)

    # ------------------------------------------------------------ 运行

    def submit(self, text, *, file_ids=(), upload_ids=(), on_event=None) -> dict:
        """同步执行一轮新 Agent 对话；结果含 status/reply/error_code。

        upload_ids 为本轮新上传的项目文件：必须进入上下文，绑定为
        explicit_upload（与勾选状态无关）；file_ids 为本轮额外勾选的历史
        文件，绑定为 explicit_selection。两者逐个校验归属，重叠时按
        explicit_upload 处理。
        """
        self._mirror_session()
        upload_ids = tuple(upload_ids)
        file_ids = tuple(fid for fid in file_ids if fid not in set(upload_ids))
        bindings = []
        if upload_ids or file_ids:
            if len(set(upload_ids)) != len(upload_ids) \
                    or len(set(file_ids)) != len(file_ids):
                raise ValueError('本轮文件范围存在重复选择')
            session = self._store.session(self._session_id)
            available = {f['id']: f for f in self._store.files(session['project'])}
            for kind, ids in (('explicit_upload', upload_ids),
                              ('explicit_selection', file_ids)):
                for file_id in ids:
                    record = available.get(file_id)
                    if record is None:
                        raise ValueError('本轮文件范围不属于当前项目或已变化')
                    bindings.append({'file_id': file_id,
                                     'sha256': record['sha256'],
                                     'binding_kind': kind})
        kernel = self._build_kernel()
        self._kernel = kernel
        error_code = []
        completed = []
        operation_ids = []

        def collector(event):
            if event.operation_id:
                # 仅在真正开工/恢复时登记 open；recovery_required 等旁路事件
                # 不得把已收束的 operation 重新计入（S1-05）。
                if event.event_type in ('operation_accepted',
                                        'operation_resumed'):
                    self._open_operations.add(event.operation_id)
                if event.operation_id not in operation_ids:
                    operation_ids.append(event.operation_id)
            if event.event_type == 'operation_failed':
                error_code.append((event.payload or {}).get('error_code',
                                                           'failed'))
            if event.event_type in ('operation_completed',
                                    'operation_failed', 'operation_aborted',
                                    'operation_unknown'):
                completed.append(event.event_type)
                if event.operation_id:
                    self._open_operations.discard(event.operation_id)

        kernel.subscribe(collector)
        if on_event is not None:
            kernel.subscribe(on_event)
        try:
            # A previous process may have died after accepting an operation.
            # Reconcile those durable open operations before admitting a new
            # turn; otherwise the stale lane remains busy forever.
            asyncio.run(kernel.recover(self._session_id))
            # S2-03：recover 收束出的 unknown operation 按服务端真实状态对账
            # （succeeded→replay / failed→本地 fail / uncertain→人工对账）。
            self._reconcile_unknown(kernel)
            asyncio.run(kernel.submit(
                self._session_id, 'main',
                {'text': text, 'model_id': self._model_id,
                 'file_bindings': bindings}))
        except Exception as exc:  # noqa: BLE001 - 网关边界不泄露堆栈
            code = getattr(exc, 'code', type(exc).__name__)
            message = str(exc).strip()
            if len(message) > 200 or any(
                    token in message.lower()
                    for token in ('token', 'bearer', 'password', 'api_key', 'secret')):
                message = ''
            return {'status': 'failed', 'reply': '', 'error_code': str(code),
                    'error_message': message,
                    'operation_id': operation_ids[-1] if operation_ids else None}
        operation_id = operation_ids[-1] if operation_ids else None
        reply = self._last_assistant_text(operation_id)
        if 'operation_completed' in completed:
            return {'status': 'completed', 'reply': reply, 'error_code': '',
                    'operation_id': operation_id}
        if 'operation_aborted' in completed:
            return {'status': 'aborted', 'reply': reply,
                    'error_code': error_code[0] if error_code else 'aborted',
                    'operation_id': operation_id}
        return {'status': 'failed', 'reply': reply,
                'error_code': error_code[0] if error_code else 'failed',
                'operation_id': operation_id}

    def _last_assistant_text(self, operation_id=None) -> str:
        entries = self.repo.entries(self._session_id, 'main')
        assistant = [e for e in entries if e.entry_type == 'assistant_message'
                     and not e.payload.get('intermediate')
                     and (operation_id is None or e.operation_id == operation_id)]
        return assistant[-1].payload.get('text', '') if assistant else ''

    # ------------------------------------------------------------ 对账

    @staticmethod
    def _sync_awaitable(value):
        if inspect.isawaitable(value):
            return asyncio.run(value)
        return value

    def _reconcile_unknown(self, kernel) -> None:
        """S2-03：对账 unknown operation。ModelPort 无对账能力（如测试替身）
        时安全跳过；单个 operation 对账失败不影响其余与新轮次。"""
        from .agent_core.reconciliation import reconcile_unknown_operation

        port = kernel.model
        query_fn = getattr(port, 'reconcile_request', None)
        if query_fn is None:
            return
        replay_fn = getattr(port, 'replay_request', None)
        for operation in self.repo.unknown_operations(self._session_id):
            try:
                reconcile_unknown_operation(
                    self.repo, operation.id,
                    query=lambda rid: self._sync_awaitable(query_fn(rid)),
                    replay=(lambda rid: self._sync_awaitable(replay_fn(rid))
                            if replay_fn is not None else None))
            except Exception:  # 对账失败保留 unknown 待下轮
                logger.warning('operation 对账失败，保留 unknown: %s',
                               operation.id, exc_info=True)

    def stop(self) -> None:
        """中止本网关全部活动 operation；无活动时安全返回。"""
        if self._kernel is None:
            return
        # The worker thread owns the asyncio loop.  Only signal cancellation
        # here; the worker loop will persist the terminal abort event.
        self._kernel.cancel_open(tuple(self._open_operations))
