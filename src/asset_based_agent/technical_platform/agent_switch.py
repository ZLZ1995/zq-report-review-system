"""S15 接线子集：app 侧装配件（ModelPort 工厂 / 批准桥 / 轮次 Worker / 灰度开关辅助）。

- client_model_port_factory：把 RemoteSessionClient 桥成 ServerModelPort 工厂；
  客户端同步 refresh() 经 asyncio.to_thread 桥进 TokenManager 的异步 refresh_fn，
  single-flight 语义由 TokenManager 自身保证；
- ApproverBridge：内核异步批准请求 → 旧 GUI 同步询问；工具的 11 类风险按
  RISK_TO_OPERATION 映射到旧权限模式的 10 类操作，复用既有弹窗与模式语义；
- AgentTurnWorker：QThread 内跑 gateway.submit，message_delta 事件转 delta
  信号、结束转 done 信号；PySide6 延迟到首次访问时导入，非 Qt 环境（纯逻辑
  测试）可正常导入本模块其余部分；
- flags_store_for / FLAG_LABELS / enabled_count：灰度开关菜单的持久化与文案。
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING

from .flags import FeatureFlagStore
from .model_port.server_model_port import ServerModelPort
from .model_port.token_provider import TokenManager

if TYPE_CHECKING:
    from collections.abc import Callable

# 新内核工具风险 → 旧权限模式操作（agent_permission_modes._OPERATIONS）。
# 只读类操作映射到 generate_file 是有意的：旧 'request' 模式对一切操作都询问，
# 映射到非 _RISKY 操作可让 'risk' 模式对只读工具免打扰，语义与旧路径一致。
RISK_TO_OPERATION = {
    'local_readonly': 'generate_file',
    'local_create': 'generate_file',
    'copy_modify': 'generate_file',
    'original_modify': 'modify_file',
    'network_read': 'network',
    'network_write': 'network',
    'browser_action': 'browser_write',
    'external_upload': 'upload',
    'credential': 'credential_use',
    'process': 'software_update',
    'update': 'software_update',
}

# 灰度类别中文标签（flags.FEATURE_FLAG_ORDER 顺序，菜单展示用）
FLAG_LABELS = {
    'chat': '普通聊天',
    'platform_query': '平台信息查询',
    'file_readonly_analysis': '文件只读分析',
    'single_readonly_skill': '单一只读 Skill',
    'local_generate_skill': '本地生成 Skill',
    'report_review': '报告审核',
    'review_annotation_copy': '审核批注副本',
    'multi_skill': '多 Skill 任务',
    'browser_readonly': '浏览器只读',
    'browser_write_upload': '浏览器写入与上传',
}


def flags_store_for(store) -> FeatureFlagStore:
    """灰度开关持久化在会话库同目录的 agent_feature_flags.json。"""
    return FeatureFlagStore(Path(store.path).parent / 'agent_feature_flags.json')


def enabled_count(flags: FeatureFlagStore) -> int:
    return sum(1 for category, on in flags.snapshot().items() if on)


def client_model_port_factory(client, *, client_version: str = ''
                              ) -> Callable[[], ServerModelPort]:
    """RemoteSessionClient → ServerModelPort 工厂；未连接服务端时 ValueError。"""
    if client is None or not getattr(client, 'access_token', None):
        raise ValueError('新 Agent 路径需要先连接服务端（缺少访问令牌）')

    async def refresh() -> str:
        # client.refresh() 是同步阻塞 HTTP；放到线程池避免卡住事件循环
        await asyncio.to_thread(client.refresh)
        return client.access_token

    def factory() -> ServerModelPort:
        return ServerModelPort(
            base_url=client.base_url,
            token_manager=TokenManager(access_token=client.access_token,
                                       refresh_fn=refresh),
            client_version=client_version,
            require_stream_capability=True)

    return factory


class ApproverBridge:
    """内核 ApprovalProvider → 旧 GUI 同步批准询问。

    ask_fn(operation, title, reason) -> bool；在 Worker 线程内被调用，
    由调用方（app 侧）负责把 ask_fn 编排到 GUI 线程。
    """

    def __init__(self, ask_fn) -> None:
        self._ask_fn = ask_fn

    async def approve(self, request) -> bool:
        operation = RISK_TO_OPERATION[request.tool.risk]
        title = f'新 Agent 请求执行工具：{request.tool.name}'
        return bool(self._ask_fn(operation, title, request.reason or ''))


def _build_worker_class():
    from PySide6.QtCore import QThread, Signal

    class AgentTurnWorker(QThread):
        """在 Worker 线程内执行一轮新 Agent 对话并向 GUI 发信号。"""

        delta = Signal(str)
        done = Signal(dict)

        def __init__(self, gateway, text, parent=None) -> None:
            super().__init__(parent)
            self.gateway = gateway  # 供 cancel_run 调用 gateway.stop()
            self._text = text

        def run(self) -> None:
            def forward(event) -> None:
                if getattr(event, 'event_type', '') == 'message_delta':
                    self.delta.emit(str((event.payload or {}).get('text', '')))

            try:
                result = self.gateway.submit(self._text, on_event=forward)
            except Exception as exc:  # noqa: BLE001 - 边界不泄露堆栈
                result = {'status': 'failed', 'reply': '',
                          'error_code': type(exc).__name__}
            self.done.emit(result)

    return AgentTurnWorker


def __getattr__(name: str):  # PEP 562：AgentTurnWorker 延迟到首次访问再导入 Qt
    if name == 'AgentTurnWorker':
        worker = _build_worker_class()
        globals()[name] = worker
        return worker
    raise AttributeError(f'module {__name__!r} has no attribute {name!r}')
