"""Turn-time memory recall: at most five, stale-flagged, evidence-first.

Current-turn file evidence outranks memory: a record that points at a file
outside the turn's selected attachments is withheld. Proposed, revoked and
superseded records never reach execution.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta
from datetime import timezone as tz

from pydantic import Field

from ..agent_contracts import Identifier, Record

RECALL_LIMIT = 5
_STALE_AFTER = timedelta(days=30)
_FILE_TOKEN = re.compile(r'[^\s，。；、]+\.(?:docx|xlsx|doc|xls|pdf)', re.IGNORECASE)


class RecallItem(Record):
    id: Identifier
    key: str = Field(min_length=1, max_length=128)
    text: str = Field(min_length=1, max_length=2000)
    scope: str
    category: str
    priority: int = Field(ge=0, le=100)
    version: int = Field(ge=1)
    stale: bool = False
    stale_reason: str = ''
    source_explanation: str = Field(min_length=1)


def _parse_moment(value):
    if not value:
        return None
    moment = datetime.fromisoformat(value)
    return moment if moment.tzinfo else moment.replace(tzinfo=tz.utc)


def select_for_turn(records, *, envelope=None, ignored_ids=frozenset(),
                    limit=RECALL_LIMIT, now=None) -> list[RecallItem]:
    if type(limit) is not int or not 1 <= limit <= 50:
        raise ValueError('召回上限必须是 1 到 50 的整数')
    moment = now or datetime.now(tz.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=tz.utc)
    ignored = set(ignored_ids)
    selected_names = set()
    if envelope is not None:
        selected_names = {item.name for item in envelope.selected_attachment_versions}

    items = []
    for record in records:
        if record.get('status') not in ('confirmed', 'active'):
            continue  # proposed 不影响执行；revoked/superseded 不再召回
        if record['id'] in ignored:
            continue
        text = record.get('text', '')
        if selected_names:
            mentioned = set(_FILE_TOKEN.findall(text))
            if mentioned and not mentioned <= selected_names:
                continue  # 记忆引用了本轮范围外文件，当前证据优先
        stale, reasons = False, []
        valid_until = _parse_moment(record.get('valid_until'))
        if valid_until is not None and valid_until <= moment:
            stale, reasons = True, ['已过有效期']
        last_verified = _parse_moment(record.get('last_verified'))
        if last_verified is not None and moment - last_verified > _STALE_AFTER:
            stale = True
            reasons.append('超过30天未验证')
        scope = record.get('scope', 'user')
        version = int(record.get('version', 1))
        items.append(RecallItem(
            id=record['id'], key=record.get('key', record['id']),
            text=text, scope=scope, category=record.get('category', 'user'),
            priority=int(record.get('priority', 50)), version=version,
            stale=stale, stale_reason='；'.join(reasons),
            source_explanation=f'来自{scope}记忆 · 版本{version}'))
    items.sort(key=lambda item: (-item.priority, item.id))
    return items[:limit]
