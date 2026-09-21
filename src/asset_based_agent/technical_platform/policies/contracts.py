"""统一权限策略合同（任务书 8.4）。

模型文本、Skill 文档和历史授权不得直接生成 allow；决策只依赖
principal、模式、Tool 风险声明、参数与文件范围。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

PERMISSION_MODES = frozenset({'request', 'assisted', 'full'})
DECISION_KINDS = frozenset({'allow', 'allow_with_restrictions', 'ask', 'deny'})


@dataclass(frozen=True)
class Principal:
    session_id: str
    operation_id: str
    owner_id: str = ''


@dataclass(frozen=True)
class FileScope:
    """本轮允许写入的根目录集合；空表示不做路径范围检查。"""
    roots: tuple = ()


@dataclass(frozen=True)
class PolicyDecision:
    kind: str
    reason: str = ''
    grants: tuple = ()
    restrictions: dict = field(default_factory=dict)

    def __post_init__(self):
        if self.kind not in DECISION_KINDS:
            raise ValueError(f'非法策略决定: {self.kind}')


@dataclass(frozen=True)
class ApprovalRequest:
    principal: Principal
    mode: str
    tool: object  # ToolDescriptor（避免 policies ↔ agent_core 循环依赖）
    arguments: dict
    reason: str = ''
    grants: tuple = ()


class PolicyEngine(Protocol):
    def evaluate(self, principal, mode, tool, arguments, file_scope):
        ...


class ApprovalProvider(Protocol):
    async def approve(self, request) -> bool:
        ...
