"""Deterministic turn-scope policy: mentions, negations and exclusions.

The policy never invents scope. A name the user typed is resolved only
against current project files; anything ambiguous or contradictory becomes a
clarification question instead of a silent choice.
"""
from __future__ import annotations

from uuid import uuid4

from .turn_context import AttachmentVersion, TurnEnvelope
from .turn_normalizer import extract_explicit_references, normalize_text

_NEGATION_TOKENS = ('不看', '不用', '排除', '不含', '除了', '不包括', '无需')
_NEGATION_WINDOW = 8
_ONLY_MARKERS = ('只', '仅')


class ScopeClarificationNeeded(ValueError):
    """The turn cannot proceed without the user resolving its file scope."""


def _negated_names(text: str, mentions: tuple[str, ...]) -> set[str]:
    lowered = text.casefold()
    result = set()
    for name in mentions:
        needle = name.casefold()
        start = 0
        while True:
            index = lowered.find(needle, start)
            if index < 0:
                break
            prefix = lowered[max(0, index - _NEGATION_WINDOW):index]
            if any(token in prefix for token in _NEGATION_TOKENS):
                result.add(name)
                break
            start = index + len(needle)
    return result


def negated_mentions(text: str, mentions) -> set[str]:
    """Public wrapper: which mentioned names are negated in the text."""
    return _negated_names(text, tuple(mentions))


def resolve_scope(*, owner, project_id, session_id, raw_user_text,
                  selected_ids, available_files, active_model_id, permission_mode,
                  newly_attached_ids=(), browser_page_identity=None,
                  prior_clarification_chain=(), locale='zh-CN',
                  timezone_name='Asia/Shanghai', clock) -> TurnEnvelope:
    """Build the immutable envelope for one turn or raise for clarification."""
    from datetime import datetime
    from datetime import timezone as tz

    normalized = normalize_text(raw_user_text)
    if not normalized:
        raise ValueError('本轮要求不能为空')
    available = {item['id']: item for item in available_files}
    selected = []
    for identity in selected_ids:
        record = available.get(identity)
        if record is None:
            raise PermissionError('本轮文件范围不属于当前项目或已变化')
        selected.append(record)
    by_name: dict[str, list[dict]] = {}
    for record in available_files:
        by_name.setdefault(record['name'], []).append(record)

    mentions = extract_explicit_references(normalized, by_name.keys())
    negated = _negated_names(normalized, mentions)
    positive_mentions = tuple(name for name in mentions if name not in negated)

    selected_names = {record['name'] for record in selected}
    for name in positive_mentions:
        if len(by_name[name]) > 1:
            versions = '、'.join(f"第 {index} 版（{item['sha256'][:10]}）"
                                for index, item in enumerate(by_name[name], 1))
            raise ScopeClarificationNeeded(
                f"本轮提到“{name}”，但项目中存在 {len(by_name[name])} 个同名版本（{versions}）。"
                '请在资料列表勾选要使用的版本后再发送。')
        if name not in selected_names:
            raise ScopeClarificationNeeded(
                f"本轮提到了“{name}”，但它没有被勾选。执行只会使用勾选的资料；"
                '请勾选该文件或修改要求。')
    for name in sorted(negated):
        if name in selected_names:
            raise ScopeClarificationNeeded(
                f"本轮要求排除“{name}”，但它仍被勾选。请取消勾选该文件或修改要求。")
    if positive_mentions and any(marker in normalized for marker in _ONLY_MARKERS):
        extra = selected_names - set(positive_mentions)
        if extra:
            raise ScopeClarificationNeeded(
                '本轮要求限定为 ' + '、'.join(positive_mentions)
                + '，但还勾选了 ' + '、'.join(sorted(extra))
                + '。请取消多余勾选或去掉“只/仅”限定。')

    excluded_ids = tuple(sorted({by_name[name][0]['id'] for name in negated}))
    excluded_set = set(excluded_ids)
    historical = tuple(sorted(set(available) - {item['id'] for item in selected}
                              - excluded_set))
    moment = clock() if clock is not None else datetime.now(tz.utc)
    return TurnEnvelope(
        owner=owner, project_id=project_id, session_id=session_id,
        turn_id=uuid4().hex, message_id=uuid4().hex,
        raw_user_text=raw_user_text, normalized_text=normalized,
        explicit_references=positive_mentions,
        selected_attachment_versions=tuple(
            AttachmentVersion(id=item['id'], name=item['name'], sha256=item['sha256'])
            for item in selected),
        newly_attached_ids=tuple(newly_attached_ids),
        historical_reference_ids=historical,
        excluded_attachment_ids=excluded_ids,
        active_model_id=active_model_id, permission_mode=permission_mode,
        browser_page_identity=browser_page_identity,
        locale=locale, timezone=timezone_name,
        submitted_at=moment.isoformat(),
        prior_clarification_chain=tuple(prior_clarification_chain),
    )


def format_scope_summary(envelope: TurnEnvelope) -> str:
    envelope = TurnEnvelope.model_validate(envelope.model_dump())
    if not envelope.selected_attachment_versions:
        return '本轮资料范围：未勾选文件（纯问答或联网任务），历史资料不会自动加入。'
    names = '、'.join(item.name for item in envelope.selected_attachment_versions)
    excluded = ''
    if envelope.excluded_attachment_ids:
        excluded = f"；本轮排除 {len(envelope.excluded_attachment_ids)} 个文件"
    return (f"本轮资料范围：{len(envelope.selected_attachment_versions)} 个文件：{names}"
            f"{excluded}。历史资料不会自动加入。")
