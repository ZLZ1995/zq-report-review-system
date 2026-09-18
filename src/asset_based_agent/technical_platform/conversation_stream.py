"""Unified conversation stream: every long stage speaks in one flow.

Model increments, parse status, Office processing, browser actions,
verification, upload and delivery all enter the same conversation stream as
ordered StreamItems projected from the workflow journal. Restoring from the
journal after a restart is idempotent — messages and artifacts are never
duplicated. There is no separate artifact column; artifacts appear as
conversation items and task details.
"""
from __future__ import annotations

from typing import Literal

from pydantic import Field

from ..agent_contracts import Record
from .workflow_events import WorkflowEvent

CHANNEL_KIND: dict[str, StreamKind] = {
    'model': 'model_delta', 'parse': 'parse_status',
    'office': 'office_progress', 'browser': 'browser_action',
    'verify': 'verification', 'upload': 'upload',
    'deliver': 'delivery'}

TERMINAL_TEXT = {'succeeded': '任务完成', 'failed': '任务失败',
                 'cancelled': '任务已取消'}

StreamKind = Literal['phase', 'node_status', 'model_delta', 'parse_status',
                     'office_progress', 'browser_action', 'verification',
                     'upload', 'delivery', 'artifact', 'terminal']


class StreamItem(Record):
    seq: int = Field(ge=1)
    kind: StreamKind
    text: str = Field(min_length=1, max_length=2_000)
    node_id: str | None = None
    at: str


def _project(event: WorkflowEvent) -> tuple[StreamKind, str] | None:
    """Map one journal event to (kind, text); None means not user-facing."""
    payload = event.payload
    node = event.node_id or ''
    if event.type == 'phase_started':
        return 'phase', f"开始阶段：{payload.get('phase', '')}"
    if event.type == 'phase_completed':
        return 'phase', f"完成阶段：{payload.get('phase', '')}"
    if event.type == 'node_queued':
        return 'node_status', f'节点 {node} 已排队'
    if event.type == 'node_started':
        return 'node_status', f'开始执行节点 {node}'
    if event.type == 'node_progress':
        channel = payload.get('channel', '')
        kind = CHANNEL_KIND.get(channel, 'node_status')
        return kind, payload.get('message', '处理中')
    if event.type in ('node_waiting_resource', 'node_waiting_user'):
        return 'node_status', payload.get('reason', f'节点 {node} 等待中')
    if event.type == 'node_retrying':
        return 'node_status', (
            f"节点 {node} 重试（第 {payload.get('attempt', '?')} 次）："
            f"{payload.get('error', '')}")
    if event.type == 'node_succeeded':
        return 'node_status', f'节点 {node} 完成'
    if event.type == 'node_failed':
        return 'node_status', f"节点 {node} 失败：{payload.get('error', '')}"
    if event.type == 'artifact_ready':
        return 'artifact', f"成果就绪：{payload.get('name', '')}"
    if event.type in ('run_terminal', 'task_completed'):
        state = payload.get('state', 'succeeded')
        return 'terminal', TERMINAL_TEXT.get(state, TERMINAL_TEXT['succeeded'])
    return None


class ConversationStream:
    """Ordered, idempotent projection of journal events for one run."""

    def __init__(self):
        self._items: list[StreamItem] = []
        self._seen: set[int] = set()

    def ingest(self, event: WorkflowEvent) -> StreamItem | None:
        if event.seq in self._seen:
            return None
        projected = _project(event)
        if projected is None:
            return None
        self._seen.add(event.seq)
        kind, text = projected
        item = StreamItem(seq=event.seq, kind=kind, text=text,
                          node_id=event.node_id, at=event.at)
        self._items.append(item)
        return item

    def items(self) -> list[StreamItem]:
        return list(self._items)

    @classmethod
    def from_journal(cls, journal, run_id: str) -> ConversationStream:
        stream = cls()
        for event in journal.events(run_id):
            stream.ingest(event)
        return stream
