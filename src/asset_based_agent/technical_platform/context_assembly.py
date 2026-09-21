"""Clarification context assembly: compact before refusing, never silently drop.

Branch reference messages (PREFIX) are identity-checked by the controller and
must pass through verbatim. Everything else may be folded into a marked
summary (non-original evidence, source ids inlined for trace-back) while the
recent tail stays verbatim. Compaction only touches the understanding working
context; the conversation store always keeps the original messages.
"""
from __future__ import annotations

from .branch_understanding import PREFIX
from .conversation_compactor import compact_messages

DEFAULT_KEEP_RECENT = 4


def compact_clarification_context(context, *, keep_recent=DEFAULT_KEEP_RECENT):
    refs = [dict(item) for item in context
            if str(item.get('id', '')).startswith(PREFIX)]
    rest = [dict(item) for item in context
            if not str(item.get('id', '')).startswith(PREFIX)]
    compacted = compact_messages(rest, keep_recent=keep_recent)
    wire = []
    for item in compacted:
        if item.get('kind') == 'summary':
            wire.append({'id': item['id'], 'role': 'assistant',
                         'text': item['text']})
        else:
            wire.append({'id': item['id'], 'role': item['role'],
                         'text': item['text']})
    return refs + wire
