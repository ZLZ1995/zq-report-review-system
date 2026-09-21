"""Append-only workflow journal: the source of truth for recovery.

Events are never mutated or deleted. A crashed run resumes from committed
nodes only; nothing committed is re-executed, so model calls are never
billed twice.
"""
from __future__ import annotations

import json
from pathlib import Path

from .workflow_events import WorkflowEvent


class WorkflowJournal:
    def __init__(self, path=None):
        self.path = Path(path) if path is not None else None
        self._events: list[WorkflowEvent] = []
        if self.path is not None and self.path.exists():
            with self.path.open(encoding='utf-8') as stream:
                for line in stream:
                    if line.strip():
                        self._events.append(WorkflowEvent.model_validate_json(line))

    def append(self, *, run_id, node_id, type, at, payload=None) -> WorkflowEvent:
        event = WorkflowEvent(seq=len(self._events) + 1, run_id=run_id,
                              node_id=node_id, type=type, at=at,
                              payload=payload or {})
        self._events.append(event)
        if self.path is not None:
            with self.path.open('a', encoding='utf-8') as stream:
                stream.write(event.model_dump_json() + '\n')
        return event

    def events(self, run_id) -> list[WorkflowEvent]:
        return [event for event in self._events if event.run_id == run_id]

    def committed_nodes(self, run_id) -> set[str]:
        return {event.node_id for event in self.events(run_id)
                if event.type == 'node_result_committed' and event.node_id}

    def terminal_state(self, run_id) -> str | None:
        terminals = [event for event in self.events(run_id)
                     if event.type == 'run_terminal']
        if not terminals:
            return None
        return terminals[-1].payload.get('state')

    def run_ids(self) -> list[str]:
        return sorted({event.run_id for event in self._events})

    @staticmethod
    def _dumps(event: WorkflowEvent) -> str:
        return json.dumps(event.model_dump(), ensure_ascii=False, sort_keys=True)
