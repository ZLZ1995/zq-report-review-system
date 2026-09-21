"""授权 Receipt：只能由 PolicyEngine 签发，绑定 Operation 与 ToolCall。

- 模型不能伪造：verify 只认本服务签发过的 receipt_id；
- 历史 receipt 不得跨 Operation/ToolCall 使用：绑定校验不符即拒绝；
- 撤销立即生效：revoke 后未开始的 ToolCall 一律拒绝；
- 不持久化：进程崩溃后未开始的调用回到询问态（安全方向）。
"""
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import uuid4

from ..agent_core.errors import ToolPermissionDenied


@dataclass(frozen=True)
class PolicyReceipt:
    receipt_id: str
    session_id: str
    operation_id: str
    tool_call_id: str
    tool_name: str
    arguments_sha256: str
    grants: tuple
    restrictions: dict
    issued_at: str


class ReceiptService:
    def __init__(self):
        self._receipts = {}
        self._revoked_sessions = set()
        self._revoked_operations = set()

    def issue(self, *, session_id, operation_id, tool_call_id, tool_name,
              arguments_sha256, grants=(), restrictions=None):
        receipt = PolicyReceipt(
            receipt_id=uuid4().hex, session_id=session_id,
            operation_id=operation_id, tool_call_id=tool_call_id,
            tool_name=tool_name, arguments_sha256=str(arguments_sha256),
            grants=tuple(grants), restrictions=dict(restrictions or {}),
            issued_at=datetime.now(timezone.utc).isoformat())
        self._receipts[receipt.receipt_id] = receipt
        return receipt

    def verify(self, receipt_id, *, operation_id, tool_call_id):
        receipt = self._receipts.get(receipt_id)
        if receipt is None:
            raise ToolPermissionDenied('授权 receipt 不存在或为伪造')
        if self.is_revoked(receipt.session_id, receipt.operation_id):
            raise ToolPermissionDenied('授权已被用户撤销')
        if receipt.operation_id != operation_id \
                or receipt.tool_call_id != tool_call_id:
            raise ToolPermissionDenied('授权 receipt 不得跨 Operation 或 ToolCall 使用')
        return receipt

    def is_revoked(self, session_id, operation_id):
        return session_id in self._revoked_sessions \
            or operation_id in self._revoked_operations

    def revoke_session(self, session_id):
        self._revoked_sessions.add(session_id)

    def revoke_operation(self, operation_id):
        self._revoked_operations.add(operation_id)
