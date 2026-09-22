"""Unified agent event protocol (任务书第 11 节核心子集)。

持久事实事件必须先提交存储再广播；message_delta 属瞬时事件，
最终必须由 message_committed 收束。
"""
import json
from dataclasses import dataclass

EVENT_TYPES = frozenset({
    'operation_accepted', 'operation_started', 'operation_waiting_input',
    'operation_waiting_approval', 'operation_suspended', 'operation_resumed',
    'operation_aborting', 'operation_completed', 'operation_failed',
    'operation_aborted', 'operation_unknown',
    'turn_started', 'model_request_started', 'message_delta',
    'message_committed', 'turn_completed', 'turn_failed',
    'tool_proposed', 'tool_authorized', 'tool_started', 'tool_progress',
    'tool_completed', 'tool_failed', 'tool_unknown',
    'artifact_created', 'balance_updated', 'recovery_required',
})

EVENT_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class AgentEvent:
    event_type: str
    session_id: str
    lane_id: str
    sequence: int
    timestamp: str
    operation_id: str | None = None
    turn_id: str | None = None
    tool_call_id: str | None = None
    payload: dict | None = None
    schema_version: int = EVENT_SCHEMA_VERSION

    def __post_init__(self):
        if self.event_type not in EVENT_TYPES:
            raise ValueError(f'非法事件类型: {self.event_type}')
        if self.payload is None:
            object.__setattr__(self, 'payload', {})

    def to_dict(self):
        return {
            'schema_version': self.schema_version,
            'sequence': self.sequence,
            'event_type': self.event_type,
            'session_id': self.session_id,
            'lane_id': self.lane_id,
            'operation_id': self.operation_id,
            'turn_id': self.turn_id,
            'tool_call_id': self.tool_call_id,
            'timestamp': self.timestamp,
            'payload': self.payload,
        }

    def to_json(self):
        return json.dumps(self.to_dict(), ensure_ascii=False)
