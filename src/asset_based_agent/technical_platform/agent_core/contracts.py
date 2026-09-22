"""Agent core contracts: model, tool, operation and policy-facing value types.

只包含纯数据与 Protocol；不得 import PySide、sqlite3 或 httpx。
"""
from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, Protocol

# ModelEvent.kind 只允许这些值（任务书 8.2）
MODEL_EVENT_KINDS = frozenset({
    'message_start', 'text_delta', 'thinking_delta', 'tool_call_delta',
    'tool_call_complete', 'usage', 'message_complete', 'request_failed',
})

TOOL_RESULT_STATUSES = frozenset({'succeeded', 'failed', 'aborted', 'unknown'})

TOOL_RISKS = frozenset({
    'local_readonly', 'local_create', 'copy_modify', 'original_modify',
    'network_read', 'network_write', 'browser_action', 'external_upload',
    'credential', 'process', 'update',
})

# S2-02 Tool Recovery Policy：中断（unknown）工具调用的恢复策略。
RECOVERY_POLICIES = frozenset({
    'safe_replay', 'idempotent_retry', 'query_before_retry',
    'manual_reconcile', 'never_retry',
})

# 未显式声明时按风险等级推导；非幂等写一律落到人工/查询后重试。
DEFAULT_RECOVERY_POLICY_BY_RISK = {
    'local_readonly': 'safe_replay',
    'network_read': 'safe_replay',
    'local_create': 'manual_reconcile',
    'copy_modify': 'manual_reconcile',
    'original_modify': 'never_retry',
    'network_write': 'query_before_retry',
    'browser_action': 'query_before_retry',
    'external_upload': 'query_before_retry',
    'credential': 'never_retry',
    'process': 'never_retry',
    'update': 'never_retry',
}

# 允许自动续跑（resume）的策略；其余必须人工核对。
AUTO_RESUME_POLICIES = frozenset({'safe_replay', 'idempotent_retry'})


@dataclass(frozen=True)
class ModelEvent:
    kind: str
    data: dict

    def __post_init__(self):
        if self.kind not in MODEL_EVENT_KINDS:
            raise ValueError(f'非法模型事件: {self.kind}')
        if not isinstance(self.data, dict):
            raise TypeError('模型事件负载必须是 dict')


@dataclass(frozen=True)
class ModelRequest:
    model_id: str
    messages: tuple
    tools: tuple = ()
    sampling: dict = field(default_factory=dict)
    request_id: str = ''
    client_version: str = ''
    protocol_version: int = 1


@dataclass(frozen=True)
class ToolDescriptor:
    name: str
    description: str
    input_schema: dict
    risk: str = 'local_readonly'
    recovery_policy: str = ''

    def __post_init__(self):
        if self.risk not in TOOL_RISKS:
            raise ValueError(f'非法工具风险等级: {self.risk}')
        if not self.name.strip():
            raise ValueError('工具名不能为空')
        if self.recovery_policy and self.recovery_policy not in RECOVERY_POLICIES:
            raise ValueError(f'非法工具恢复策略: {self.recovery_policy}')

    @property
    def effective_recovery_policy(self) -> str:
        """显式声明优先；否则按风险等级推导（S2-02）。"""
        return (self.recovery_policy
                or DEFAULT_RECOVERY_POLICY_BY_RISK[self.risk])


@dataclass(frozen=True)
class ToolResult:
    status: str
    content: str = ''
    result: Any = None
    artifacts: tuple = ()
    receipts: tuple = ()
    error_code: str = ''
    diagnostics_ref: str = ''

    def __post_init__(self):
        if self.status not in TOOL_RESULT_STATUSES:
            raise ValueError(f'非法工具结果状态: {self.status}')


@dataclass(frozen=True)
class OperationAccepted:
    operation_id: str
    session_id: str
    lane_id: str
    request_id: str


class ModelPort(Protocol):
    def stream(self, request: ModelRequest, cancel) -> AsyncIterator[ModelEvent]:
        ...


class AgentTool(Protocol):
    descriptor: ToolDescriptor

    async def execute(self, context, arguments: dict, cancel) -> ToolResult:
        ...


class EventListener(Protocol):
    def __call__(self, event) -> None:
        ...
