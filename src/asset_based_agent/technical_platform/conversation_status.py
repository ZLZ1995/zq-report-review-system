"""S16：会话/轮次级状态控制器——替代单一固定状态栏。

规则（施工文件 4.2）：
- 会话状态必须携带 session_id；异步回调必须携带 operation_id；
- 当前 UI 只渲染当前 session 的状态；旧会话状态保留但不污染新会话；
- 完成后临时阶段卡被终态替换，不形成重复内容；
- 全局通知（连接/更新/浏览器）按 kind 存取，与轮次状态互不干扰。
"""
from __future__ import annotations

from dataclasses import dataclass, field

TERMINAL_PHASES = frozenset({'completed', 'failed', 'cancelled', 'waiting'})
ACTIVE_PHASES = frozenset({'running'})


@dataclass(frozen=True)
class TurnStatus:
    session_id: str
    operation_id: str
    phase: str  # 'running' | 'completed' | 'failed' | 'cancelled' | 'waiting'
    text: str
    payload: dict = field(default_factory=dict)


class ConversationStatusController:
    """纯内存控制器：状态是易失的，持久化只落关键事件（由 store 层负责）。"""

    def __init__(self) -> None:
        self._turns: dict[tuple[str, str], TurnStatus] = {}
        self._order: list[tuple[str, str]] = []  # 写入顺序，用于会话最新相位
        self._notices: dict[str, str] = {}

    # ------------------------------------------------------------ 轮次状态

    def set_turn_phase(self, session_id: str, operation_id: str, text: str
                       ) -> None:
        self._put(session_id, operation_id, 'running', text)

    def complete_turn(self, session_id: str, operation_id: str, summary: str
                      ) -> None:
        self._put(session_id, operation_id, 'completed', summary)

    def fail_turn(self, session_id: str, operation_id: str, error_code: str,
                  summary: str) -> None:
        self._put(session_id, operation_id, 'failed', summary,
                  payload={'error_code': error_code})

    def cancel_turn(self, session_id: str, operation_id: str, summary: str
                    ) -> None:
        self._put(session_id, operation_id, 'cancelled', summary)

    def clear_turn_phase(self, session_id: str, operation_id: str) -> None:
        key = (session_id, operation_id)
        self._turns.pop(key, None)

    def turn_phase(self, session_id: str, operation_id: str | None = None
                   ) -> TurnStatus | None:
        if operation_id is not None:
            return self._turns.get((session_id, operation_id))
        for key in reversed(self._order):
            if key[0] == session_id and key in self._turns:
                return self._turns[key]
        return None

    def _put(self, session_id: str, operation_id: str, phase: str, text: str,
             payload: dict | None = None) -> None:
        if not session_id or not operation_id:
            raise ValueError('会话状态必须携带 session_id 与 operation_id')
        key = (session_id, operation_id)
        if key not in self._turns:
            self._order.append(key)
        self._turns[key] = TurnStatus(session_id=session_id,
                                      operation_id=operation_id,
                                      phase=phase, text=text,
                                      payload=payload or {})

    # ------------------------------------------------------------ 全局通知

    def set_global_notice(self, kind: str, text: str | None) -> None:
        if text is None:
            self._notices.pop(kind, None)
        else:
            self._notices[kind] = text

    def global_notice(self, kind: str) -> str | None:
        return self._notices.get(kind)
