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

from .agent_core.context_builder import ContextBuilder
from .agent_core.runtime import AgentKernel
from .business_tools import business_tools
from .business_tools.service import BusinessRunService
from .flags import FEATURE_FLAG_ORDER
from .policies.engine import RuleBasedPolicyEngine
from .sessions.sqlite_repository import SQLiteSessionRepo
from .tools.browser_tools import BrowserToolError, build_browser_tools

MODE_MAP = {'request': 'request', 'risk': 'assisted', 'full': 'full'}

_SKILL_CATEGORIES = frozenset({
    'single_readonly_skill', 'local_generate_skill', 'report_review',
    'multi_skill'})

_BUSINESS_TOOL_CATEGORY = {
    'inspect_project_files': 'file_readonly_analysis',
    'analyze_file_roles': 'file_readonly_analysis',
    'list_final_artifacts': 'file_readonly_analysis',
    'annotate_reviewed_files': 'review_annotation_copy',
    # execute/query/cancel 属于任一 Skill 类别
}

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
                 force_all_tools: bool = False) -> None:
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
        service = BusinessRunService(self._store, self._session_id,
                                     provider_factory=self._provider_factory)
        for tool in business_tools(service):
            name = tool.descriptor.name
            category = _BUSINESS_TOOL_CATEGORY.get(name)
            if category is not None:
                if self._enabled(category):
                    tools.append(tool)
            elif any(self._enabled(c) for c in _SKILL_CATEGORIES):
                tools.append(tool)
        if self._enabled('browser_readonly') \
                or self._enabled('browser_write_upload'):
            backend = self._browser_backend or NullBrowserBackend()
            write = self._enabled('browser_write_upload')
            for tool in build_browser_tools(self._session_id, backend):
                if tool.descriptor.name in _BROWSER_READONLY_TOOLS or write:
                    tools.append(tool)
        return tuple(tools)

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
        kernel = AgentKernel(
            repo=self.repo, model=self._model_port_factory(),
            tools=self.active_tools(), policy=RuleBasedPolicyEngine(),
            approver=self._approver, context_builder=ContextBuilder())
        self._kernel = kernel
        error_code = []
        completed = []

        def collector(event):
            if event.operation_id:
                self._open_operations.add(event.operation_id)
            if event.event_type == 'operation_failed':
                error_code.append((event.payload or {}).get('error_code',
                                                           'failed'))
            if event.event_type in ('operation_completed',
                                    'operation_failed', 'operation_aborted'):
                completed.append(event.event_type)
                if event.operation_id:
                    self._open_operations.discard(event.operation_id)

        kernel.subscribe(collector)
        if on_event is not None:
            kernel.subscribe(on_event)
        try:
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
                    'error_message': message}
        reply = self._last_assistant_text()
        if 'operation_completed' in completed:
            return {'status': 'completed', 'reply': reply, 'error_code': ''}
        if 'operation_aborted' in completed:
            return {'status': 'aborted', 'reply': reply,
                    'error_code': error_code[0] if error_code else 'aborted'}
        return {'status': 'failed', 'reply': reply,
                'error_code': error_code[0] if error_code else 'failed'}

    def _last_assistant_text(self) -> str:
        entries = self.repo.entries(self._session_id, 'main')
        assistant = [e for e in entries if e.entry_type == 'assistant_message'
                     and not e.payload.get('intermediate')]
        return assistant[-1].payload.get('text', '') if assistant else ''

    def stop(self) -> None:
        """中止本网关全部活动 operation；无活动时安全返回。"""
        if self._kernel is None:
            return
        for operation_id in list(self._open_operations):
            try:
                asyncio.run(self._kernel.abort(operation_id))
            except Exception as exc:  # noqa: BLE001 - 停止路径尽力而为
                import logging
                logging.getLogger(__name__).warning(
                    'abort operation %s failed: %s', operation_id,
                    type(exc).__name__)
            finally:
                self._open_operations.discard(operation_id)
