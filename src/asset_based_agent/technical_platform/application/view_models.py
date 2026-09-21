"""ViewModel：纯数据展示状态；不持有 repo/store/db 句柄（UI 规则）。"""
from dataclasses import dataclass


@dataclass
class DisplayItem:
    key: str
    kind: str  # user/assistant/streaming/tool_call/tool_result/artifact/error/system
    text: str
    artifacts: tuple = ()
    final: bool = True


class ConversationViewModel:
    """单个 lane 的展示状态；rebuild 幂等，可从 Entry 全量重建。"""

    def __init__(self, session_id, lane_id):
        self.session_id = session_id
        self.lane_id = lane_id
        self.items = []
        self._streams = {}

    def rebuild(self, entries):
        items = []
        for entry in entries:
            payload = entry.payload or {}
            if entry.entry_type == 'user_message':
                items.append(DisplayItem(entry.id, 'user',
                                         payload.get('text', '')))
            elif entry.entry_type == 'assistant_message':
                items.append(DisplayItem(entry.id, 'assistant',
                                         payload.get('text', '')))
            elif entry.entry_type == 'tool_call':
                items.append(DisplayItem(
                    entry.id, 'tool_call', f"调用工具 {payload.get('name', '')}"))
            elif entry.entry_type == 'tool_result':
                items.append(DisplayItem(
                    entry.id, 'tool_result',
                    payload.get('content', '')
                    or f"工具结果（{payload.get('status', '')}）"))
                names = tuple(
                    a.get('name') for a in (payload.get('result') or {}).get('artifacts', [])
                    if isinstance(a, dict) and a.get('name'))
                if names:  # 最终 Artifact 直接显示在对话中
                    items.append(DisplayItem(f'{entry.id}:artifacts', 'artifact',
                                             '本轮最终成果', artifacts=names))
            elif entry.entry_type == 'error_message':
                items.append(DisplayItem(entry.id, 'error',
                                         payload.get('text', '')))
            elif entry.entry_type == 'context_summary':
                items.append(DisplayItem(entry.id, 'system',
                                         payload.get('text', '')))
        self.items = [*items, *[DisplayItem(f'stream:{turn}', 'streaming',
                                            text, final=False)
                                for turn, text in self._streams.items()]]

    def apply_delta(self, turn_id, text):
        key = f'stream:{turn_id}'
        self._streams[turn_id] = self._streams.get(turn_id, '') + text
        for item in self.items:
            if item.key == key:
                item.text = self._streams[turn_id]
                return
        self.items.append(DisplayItem(key, 'streaming',
                                      self._streams[turn_id], final=False))

    def finalize_stream(self, turn_id):
        self._streams.pop(turn_id, None)
        self.items = [item for item in self.items
                      if item.key != f'stream:{turn_id}']


@dataclass
class SessionViewModel:
    session_id: str
    title: str = ''
    status: str = 'idle'  # idle/running/failed —— session-scoped，取代全局 banner
    unread: int = 0
