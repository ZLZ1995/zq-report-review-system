"""Task panel projection over the workflow journal.

The panel shows real phases, the current node, completed/total counts, the
explicit wait reason, last activity time and whether the run can still be
cancelled. Percentages are auxiliary only — progress text always carries
counts and the current explanation, never a bare unexplained number.
"""
from __future__ import annotations

from typing import Literal

from pydantic import Field

from ..agent_contracts import Identifier, Record

NODE_TERMINAL = ('node_succeeded', 'node_failed')
NODE_WAITING = ('node_waiting_resource', 'node_waiting_user')


class TaskPanelState(Record):
    run_id: Identifier
    phase: str | None = None
    current_node: str | None = None
    completed_nodes: int = Field(ge=0)
    total_nodes: int = Field(ge=0)
    wait_reason: str | None = None
    last_activity_at: str | None = None
    cancellable: bool = True
    terminal: Literal['succeeded', 'failed', 'cancelled'] | None = None


def project_panel(journal, run_id: str) -> TaskPanelState:
    events = journal.events(run_id) if hasattr(journal, 'events') else [
        event for event in journal if event.run_id == run_id]
    queued: set[str] = set()
    node_status: dict[str, str] = {}
    pending_wait: dict[str, str] = {}
    phase: str | None = None
    terminal = None
    last_activity_at = None
    for event in events:
        last_activity_at = event.at
        if event.type == 'node_queued' and event.node_id:
            queued.add(event.node_id)
            node_status.setdefault(event.node_id, 'queued')
        elif event.type in ('node_started', 'node_progress', 'node_retrying',
                            *NODE_WAITING, *NODE_TERMINAL) and event.node_id:
            status = {'node_started': 'running', 'node_progress': 'running',
                      'node_retrying': 'retrying',
                      'node_waiting_resource': 'waiting_resource',
                      'node_waiting_user': 'waiting_user',
                      'node_succeeded': 'succeeded',
                      'node_failed': 'failed'}[event.type]
            node_status[event.node_id] = status
            if event.type in NODE_WAITING:
                pending_wait[event.node_id] = event.payload.get('reason', '')
            else:
                pending_wait.pop(event.node_id, None)
        elif event.type == 'phase_started':
            phase = event.payload.get('phase', phase)
        elif event.type == 'phase_completed':
            if phase == event.payload.get('phase'):
                phase = None
        elif event.type == 'run_terminal':
            terminal = event.payload.get('state')
    completed = sum(1 for status in node_status.values()
                    if status in ('succeeded', 'failed'))
    current_node = None
    if terminal is None:
        for event in reversed(events):
            if (event.node_id
                    and node_status.get(event.node_id) not in ('succeeded', 'failed')):
                current_node = event.node_id
                break
    wait_reason = None
    if pending_wait:
        latest_seq = -1
        for event in events:
            if (event.type in NODE_WAITING and event.node_id in pending_wait
                    and event.seq > latest_seq):
                latest_seq = event.seq
                wait_reason = pending_wait[event.node_id]
    return TaskPanelState(
        run_id=run_id, phase=phase, current_node=current_node,
        completed_nodes=completed, total_nodes=len(queued),
        wait_reason=wait_reason, last_activity_at=last_activity_at,
        cancellable=terminal is None,
        terminal=terminal)


def progress_text(state: TaskPanelState) -> str:
    """Human-readable progress: counts first, percentage auxiliary only."""
    parts = [f'{state.completed_nodes}/{state.total_nodes} 节点完成']
    if state.phase:
        parts.append(f'阶段：{state.phase}')
    if state.current_node:
        parts.append(f'当前节点 {state.current_node}')
    if state.wait_reason:
        parts.append(f'等待：{state.wait_reason}')
    if state.terminal:
        label = {'succeeded': '已完成', 'failed': '已失败',
                 'cancelled': '已取消',
                 'waiting_user': '等待补充信息'}.get(state.terminal, state.terminal)
        parts.append(label)
    if state.total_nodes:
        percent = state.completed_nodes * 100 // state.total_nodes
        parts.append(f'（{percent}%）')
    return '，'.join(parts)
