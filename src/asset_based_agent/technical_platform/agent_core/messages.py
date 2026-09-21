"""Conversation entry model: append-only, tree-structured per lane."""
from dataclasses import dataclass

ENTRY_TYPES = frozenset({
    'user_message', 'assistant_message', 'tool_call', 'tool_result',
    'system_note', 'context_summary', 'artifact_reference', 'error_message',
})

SCHEMA_VERSION = 1


@dataclass(frozen=True)
class ConversationEntry:
    id: str
    session_id: str
    lane_id: str
    parent_id: str | None
    sequence: int
    entry_type: str
    payload: dict
    operation_id: str | None
    turn_id: str | None
    schema_version: int
    created_at: str

    def __post_init__(self):
        if self.entry_type not in ENTRY_TYPES:
            raise ValueError(f'非法 Entry 类型: {self.entry_type}')
        if self.sequence < 1:
            raise ValueError('Entry sequence 必须从 1 开始')
        if not isinstance(self.payload, dict):
            raise TypeError('Entry payload 必须是 dict')
