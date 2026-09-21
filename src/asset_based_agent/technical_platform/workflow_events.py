"""Unified workflow event vocabulary (G07 runtime + G09 conversation stream)."""
from __future__ import annotations

from typing import Literal

from pydantic import Field

from ..agent_contracts import Identifier, Record

EVENT_TYPES = ('run_created', 'phase_started', 'phase_completed',
               'node_queued', 'node_claimed', 'node_started', 'node_progress',
               'node_waiting_resource', 'node_waiting_user', 'node_retrying',
               'node_succeeded', 'node_result_committed', 'node_failed',
               'permission', 'resource', 'artifact', 'artifact_ready',
               'run_terminal', 'task_completed')


class WorkflowEvent(Record):
    seq: int = Field(ge=1)
    run_id: Identifier
    node_id: Identifier | None = None
    type: Literal['run_created', 'phase_started', 'phase_completed',
                  'node_queued', 'node_claimed', 'node_started', 'node_progress',
                  'node_waiting_resource', 'node_waiting_user', 'node_retrying',
                  'node_succeeded', 'node_result_committed', 'node_failed',
                  'permission', 'resource', 'artifact', 'artifact_ready',
                  'run_terminal', 'task_completed']
    at: str = Field(min_length=1, max_length=64)
    payload: dict[str, str] = Field(default_factory=dict, max_length=20)
