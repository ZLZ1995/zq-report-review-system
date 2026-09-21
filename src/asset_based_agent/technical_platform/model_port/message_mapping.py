"""会话 Entry 历史 → 线格式消息。

输出只含 ``{role, content}`` 文本消息：不携带文件路径字段、二进制或
base64 负载（服务端 schema extra='forbid' 从结构上再次强制）。tool 历史
文本化为确定性标记格式；error_message 与空白消息不回灌模型。
"""
from __future__ import annotations

import json


def entries_to_wire_messages(entries) -> list[dict[str, str]]:
    wire: list[dict[str, str]] = []
    for entry in entries:
        mapper = _MAPPERS.get(entry.get('role'))
        if mapper is None:
            continue  # error_message 等类型不回灌模型
        message = mapper(entry.get('payload') or {})
        if message['content'].strip():
            wire.append(message)
    return wire


def _text(payload) -> str:
    return str(payload.get('text') or '')


def _user(payload):
    return {'role': 'user', 'content': _text(payload)}


def _assistant(payload):
    return {'role': 'assistant', 'content': _text(payload)}


def _system(payload):
    return {'role': 'system', 'content': _text(payload)}


def _tool_call(payload):
    name = str(payload.get('name') or '')
    canonical = json.dumps(payload.get('arguments'), ensure_ascii=False,
                           sort_keys=True)
    return {'role': 'assistant', 'content': f'[工具调用] {name}: {canonical}'}


def _tool_result(payload):
    name = str(payload.get('name') or '')
    content = payload.get('content')
    if content is None or content == '':
        content = payload.get('result')
    return {'role': 'user', 'content': f'[工具结果] {name}: {content}'}


def _context_summary(payload):
    return {'role': 'system', 'content': f'[上下文摘要] {_text(payload)}'}


def _artifact_reference(payload):
    summary = payload.get('summary') or payload.get('ref') or ''
    return {'role': 'user', 'content': f'[产物引用] {summary}'}


_MAPPERS = {
    'user_message': _user,
    'assistant_message': _assistant,
    'system_note': _system,
    'tool_call': _tool_call,
    'tool_result': _tool_result,
    'context_summary': _context_summary,
    'artifact_reference': _artifact_reference,
}
