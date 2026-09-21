"""客户端 SSE 行解析：`event:`/`data:` 帧 → (kind, data dict)。

坏 JSON 一律归类为 ModelProtocolError，不得裸抛 ValueError。
"""
from __future__ import annotations

import json
from typing import TYPE_CHECKING

from ..agent_core.errors import ModelProtocolError

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


async def iter_sse_events(
    lines: AsyncIterator[str],
) -> AsyncIterator[tuple[str, dict]]:
    event: str | None = None
    data_lines: list[str] = []
    async for raw in lines:
        line = raw.rstrip('\r')
        if line.startswith('event: '):
            event = line[len('event: '):].strip()
        elif line.startswith('data: '):
            data_lines.append(line[len('data: '):])
        elif line.strip() == '':
            if event is None and not data_lines:
                continue  # 心跳/注释帧
            yield _frame(event, data_lines)
            event, data_lines = None, []
    if event is not None or data_lines:
        yield _frame(event, data_lines)  # 流末尾未以空行收束的残帧


def _frame(event: str | None, data_lines: list[str]) -> tuple[str, dict]:
    payload = ''.join(data_lines)
    try:
        data = json.loads(payload) if payload else {}
    except ValueError as exc:
        raise ModelProtocolError(
            f'服务端事件帧不是合法 JSON: {payload[:80]}') from exc
    if not isinstance(data, dict):
        raise ModelProtocolError('服务端事件帧负载必须是对象')
    return (event or 'message'), data
