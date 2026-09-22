"""S16：对话时间线投影——messages + run_message_links → 稳定 TimelineItem 序列。

规则（施工文件 2.1/4.3）：
- 顺序：用户消息 → 本轮 live 状态 → 助手回复 → 该轮成果 → 下一轮…；
- 成果紧跟产生它的 assistant 消息（relation exact/legacy_inferred）；
- 普通聊天不带出任何历史成果；
- legacy_unlinked 及无关联旧 run 进入独立旧成果区域，不挂在最新回复下；
- 进行中（queued/running/validating）的 run 不进入任何成果区；
- 纯函数：不触库、不触 Qt，渲染由调用方负责。
"""
from __future__ import annotations

from dataclasses import dataclass, field

ACTIVE_RUN_STATES = frozenset({'queued', 'running', 'validating'})
LINKED_RELATIONS = frozenset({'exact', 'legacy_inferred'})

ITEM_KINDS = frozenset({
    'user', 'assistant', 'event', 'live_user', 'live_status', 'artifacts',
    'legacy_artifacts',
})


def project_agent_timeline(entries, *, live_status=None) -> list[TimelineItem]:
    """Project the new Agent repository entries into user-visible messages.

    The legacy Qt store is deliberately not consulted here.  The Agent kernel
    already persists one ``user_message`` at operation acceptance and one
    terminal ``assistant_message`` (or ``error_message``).  Tool calls/results
    and intermediate assistant text are execution internals and must not be
    rendered as a second conversational answer.
    """
    items: list[TimelineItem] = []
    seen = set()
    for entry in entries or ():
        entry_id = getattr(entry, 'id', None)
        if entry_id in seen:
            continue
        seen.add(entry_id)
        entry_type = getattr(entry, 'entry_type', '')
        payload = dict(getattr(entry, 'payload', {}) or {})
        if entry_type == 'user_message':
            kind = 'user'
        elif entry_type == 'assistant_message':
            if payload.get('intermediate'):
                continue
            kind = 'assistant'
        elif entry_type == 'error_message':
            kind = 'event'
        else:
            continue
        items.append(TimelineItem(
            kind=kind,
            message_id=entry_id,
            operation_id=getattr(entry, 'operation_id', None),
            created_at=getattr(entry, 'created_at', '') or '',
            payload={
                'text': str(payload.get('text', '')),
                **({'_legacy_message_id': str(payload['_legacy_message_id'])}
                   if payload.get('_legacy_message_id') else {}),
            },
        ))
    if live_status:
        user_text = str(live_status.get('user_text', '')).strip()
        if user_text and not any(
                item.kind == 'user' and item.payload.get('text') == user_text
                for item in items):
            items.append(TimelineItem(
                kind='live_user',
                operation_id=live_status.get('operation_id'),
                payload={'text': user_text},
            ))
        items.append(TimelineItem(
            kind='live_status',
            operation_id=live_status.get('operation_id'),
            payload={'text': live_status.get('text', '')},
        ))
    return items


@dataclass(frozen=True)
class TimelineItem:
    kind: str
    message_id: int | None = None
    run_id: str | None = None
    operation_id: str | None = None
    created_at: str = ''
    payload: dict = field(default_factory=dict)

    def __post_init__(self):
        if self.kind not in ITEM_KINDS:
            raise ValueError(f'非法时间线条目类型: {self.kind}')


def project_timeline(messages: list[dict], links: list[dict],
                     runs: list[dict], *, live_status: dict | None = None,
                     agent_entries=None) -> list[TimelineItem]:
    """把会话数据投影成线性 TimelineItem 序列。

    messages：store.messages() 行（id/role/text/created，按 id 升序）；
    links：store.run_links() 行；
    runs：store.runs() 行；
    live_status：当前轮次 {'after_message_id', 'text', 'operation_id'} 或 None。
    """
    if agent_entries:
        agent_items = project_agent_timeline(
            agent_entries, live_status=live_status)
        legacy_items = project_timeline(
            messages, links, runs, live_status=None)
        mirrored_ids = {
            item.payload['_legacy_message_id'] for item in agent_items
            if item.kind in {'user', 'assistant', 'event'}
            and item.payload.get('_legacy_message_id')
        }
        mirrored_entry_ids = {
            item.payload['_legacy_message_id']: item.message_id
            for item in agent_items
            if item.kind in {'user', 'assistant', 'event'}
            and item.payload.get('_legacy_message_id')
        }
        # Match mirrored rows by durable source ID, never by text: users can
        # legitimately send the same message several times in one session.
        legacy_items = [item for item in legacy_items if not (
            item.kind in {'user', 'assistant', 'event'}
            and str(item.message_id) in mirrored_ids)]

        # Run links still reference legacy assistant IDs. Re-anchor those
        # artifacts to the exact mirrored Agent entry before removing the
        # legacy message copy, so migration does not strand old files.
        from dataclasses import replace
        legacy_items = [
            replace(item, message_id=mirrored_entry_ids[
                str(item.message_id)])
            if item.kind == 'artifacts'
            and str(item.message_id) in mirrored_entry_ids else item
            for item in legacy_items
        ]

        # Preserve artifact anchors while merging both stores by event time.
        # Sorting a flat list would detach artifacts from their assistant row;
        # therefore collect them by anchor and emit immediately after it.
        artifacts_by_message = {}
        legacy_zone = []
        legacy_messages = []
        for item in legacy_items:
            if item.kind == 'artifacts':
                artifacts_by_message.setdefault(item.message_id, []).append(item)
            elif item.kind == 'legacy_artifacts':
                legacy_zone.append(item)
            else:
                legacy_messages.append(item)
        live_items = [item for item in agent_items
                      if item.kind in {'live_user', 'live_status'}]
        conversational = [item for item in agent_items
                          if item.kind not in {'live_user', 'live_status'}]
        merged = legacy_messages + conversational
        merged.sort(key=lambda item: (item.created_at or '',
                                      0 if item.kind == 'user' else 1,
                                      item.message_id or 0))
        ordered = []
        for item in merged:
            ordered.append(item)
            if item.kind == 'assistant' and item.message_id in artifacts_by_message:
                ordered.extend(artifacts_by_message.pop(item.message_id))
        # Orphan artifacts are retained in a separate zone, never attached to
        # the most recent Agent response by accident.
        orphan_artifacts = [artifact for group in artifacts_by_message.values()
                            for artifact in group]
        if orphan_artifacts:
            legacy_zone.append(TimelineItem(
                kind='legacy_artifacts',
                payload={'runs': [item.payload.get('run', {})
                                  for item in orphan_artifacts]}))
        return ordered + live_items + legacy_zone

    runs_by_id = {run['id']: run for run in runs}
    # assistant 消息 → 关联 run（保持 runs 原有顺序）
    anchored: dict[int, list[dict]] = {}
    linked_run_ids = set()
    for entry in links:
        assistant_id = entry.get('assistant_message_id')
        run_id = entry.get('run_id')
        if (entry.get('relation') in LINKED_RELATIONS
                and assistant_id is not None and run_id in runs_by_id):
            anchored.setdefault(assistant_id, []).append(runs_by_id[run_id])
            linked_run_ids.add(run_id)

    items: list[TimelineItem] = []
    live_inserted = False
    live_anchor = (live_status or {}).get('after_message_id')
    for message in messages:
        role = message.get('role')
        kind = role if role in ('user', 'assistant', 'event') else 'event'
        items.append(TimelineItem(
            kind=kind, message_id=message.get('id'),
            created_at=message.get('created', ''),
            payload={'text': message.get('text', '')}))
        if (not live_inserted and live_status and live_anchor is not None
                and message.get('id') == live_anchor):
            items.append(TimelineItem(
                kind='live_status',
                operation_id=live_status.get('operation_id'),
                payload={'text': live_status.get('text', '')}))
            live_inserted = True
        if kind == 'assistant':
            for run in anchored.get(message.get('id'), ()):
                items.append(TimelineItem(
                    kind='artifacts', message_id=message.get('id'),
                    run_id=run['id'], created_at=run.get('created', ''),
                    payload={'run': run}))
    if live_status and not live_inserted:
        # 锚点消息尚未落库（极端时序）：追加在末尾，绝不丢失
        user_text = str(live_status.get('user_text', '')).strip()
        if user_text:
            items.append(TimelineItem(
                kind='live_user', operation_id=live_status.get('operation_id'),
                payload={'text': user_text}))
        items.append(TimelineItem(
            kind='live_status', operation_id=live_status.get('operation_id'),
            payload={'text': live_status.get('text', '')}))

    # 独立旧成果区：legacy_unlinked 或无关联行的终态 run
    legacy = []
    linked_or_tracked = linked_run_ids | {
        entry['run_id'] for entry in links if entry.get('run_id')}
    for run in runs:
        if run['id'] in linked_run_ids or run.get('state') in ACTIVE_RUN_STATES:
            continue
        if run['id'] not in linked_or_tracked:
            legacy.append(run)  # 无关联行的极端旧数据
        else:
            relation = next(entry.get('relation') for entry in links
                            if entry.get('run_id') == run['id'])
            if relation == 'legacy_unlinked':
                legacy.append(run)
    if legacy:
        items.append(TimelineItem(kind='legacy_artifacts',
                                  payload={'runs': legacy}))
    return items
