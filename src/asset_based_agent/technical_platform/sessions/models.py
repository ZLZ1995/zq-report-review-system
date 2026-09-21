"""Session repository record models."""

OPERATION_KINDS = frozenset({'consult', 'execution', 'browser', 'query'})

OPERATION_STATUSES = frozenset({
    'accepted', 'running', 'waiting_input', 'waiting_approval', 'deferred',
    'suspended', 'aborting', 'completed', 'failed', 'aborted', 'declined',
    'unknown',
})

OPEN_STATUSES = frozenset({
    'accepted', 'running', 'waiting_input', 'waiting_approval',
    'deferred', 'suspended', 'aborting',
})

SESSION_SCHEMA_VERSION = 1

TURN_OPEN_STATUSES = frozenset(
    {'queued', 'model_streaming', 'tool_batch', 'awaiting_continuation'})
TOOL_CALL_OPEN_STATUSES = frozenset({'proposed', 'running'})

BINDING_KINDS = frozenset({
    'explicit_upload', 'explicit_selection', 'explicit_mention',
    'agent_discovered', 'project_reference', 'historical_reference',
    'generated_artifact'})
EXPLICIT_BINDING_KINDS = frozenset(
    {'explicit_upload', 'explicit_selection', 'explicit_mention'})

FACT_STATUS_TRANSITIONS = {
    'proposed': frozenset({'confirmed', 'rejected'}),
    'confirmed': frozenset({'superseded'}),
    'rejected': frozenset(),
    'superseded': frozenset()}


class Turn:
    """agent_turns 行记录。"""

    def __init__(self, *, id, operation_id, ordinal, status,
                 input_context_sha256, model_request_id=None,
                 assistant_entry_id=None, started_at=None, finished_at=None,
                 error_code=None, usage=None):
        self.id = id
        self.operation_id = operation_id
        self.ordinal = ordinal
        self.status = status
        self.model_request_id = model_request_id
        self.input_context_sha256 = input_context_sha256
        self.assistant_entry_id = assistant_entry_id
        self.started_at = started_at
        self.finished_at = finished_at
        self.error_code = error_code
        self.usage = usage or {}


class ToolCall:
    """agent_tool_calls 行记录。"""

    def __init__(self, *, id, operation_id, turn_id, tool_name, arguments,
                 arguments_sha256, risk_level, idempotency_key, status,
                 authorization_id=None, result_entry_id=None, started_at=None,
                 finished_at=None, error_code=None):
        self.id = id
        self.operation_id = operation_id
        self.turn_id = turn_id
        self.tool_name = tool_name
        self.arguments = arguments
        self.arguments_sha256 = arguments_sha256
        self.risk_level = risk_level
        self.authorization_id = authorization_id
        self.status = status
        self.result_entry_id = result_entry_id
        self.idempotency_key = idempotency_key
        self.started_at = started_at
        self.finished_at = finished_at
        self.error_code = error_code


class Operation:
    """Durable operation record（与 agent_core.fakes.Operation 同契约）。"""

    def __init__(self, *, id, session_id, lane_id, request_id, source_entry_id,
                 kind='consult', status='running', current_turn_id=None,
                 error_code=None, error_summary=None, accepted_at=None,
                 started_at=None, finished_at=None, recovery_policy='manual',
                 model_id=None):
        self.id = id
        self.session_id = session_id
        self.lane_id = lane_id
        self.kind = kind
        self.status = status
        self.request_id = request_id
        self.model_id = model_id
        self.source_entry_id = source_entry_id
        self.current_turn_id = current_turn_id
        self.error_code = error_code
        self.error_summary = error_summary
        self.accepted_at = accepted_at
        self.started_at = started_at
        self.finished_at = finished_at
        self.recovery_policy = recovery_policy
