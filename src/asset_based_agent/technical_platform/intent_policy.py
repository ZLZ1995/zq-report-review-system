"""Deterministic pre-parse and local adjudication of model intents.

Four-stage pipeline: `preparse` extracts deterministic signals; the model
returns a strict `ModelIntent`; `adjudicate` binds it to the TurnEnvelope
(objects must come from the envelope, business red lines outrank the model,
conflicts become clarification questions); only plan-changing questions are
asked. The model never grants tool permissions: capabilities outside the
whitelist are dropped and can never reach execution.
"""
from __future__ import annotations

import json
import re
from hashlib import sha256

from .intent_schema import AdjudicatedIntent, ModelIntent, ParsedSignals
from .turn_context import TurnEnvelope, envelope_hash
from .turn_normalizer import extract_explicit_references, normalize_text
from .turn_scope_policy import negated_mentions

ALLOWED_CAPABILITIES = ('report.review', 'review.preflight',
                        'valuation-detail-workbook-fill', 'gongshang-change-history-docx',
                        'financial-brief-docx', 'office-workflow-to-skill', 'browser.task')
NO_TARGET_CAPABILITIES = frozenset({'office-workflow-to-skill', 'browser.task'})

_ACTION_TOKENS = ('审核', '核对', '填写', '生成', '对比', '汇总', '合并',
                  '下载', '上传', '登录', '安装', '取消', '修改', '发送', '录制')
_CANCEL_TOKENS = ('算了', '别做了', '取消', '不用做了', '先别做')
_AUTHORIZATION_TOKENS = ('已授权', '已经授权', '获得授权', '已获授权')
_CONDITION_TOKENS = ('如果', '若', '当', '只要', '除非', '万一', '要是')
_TIME_TOKENS = ('今天', '昨天', '明天', '上周', '本周', '本月', '上次',
                '刚才', '最新', '上年', '今年', '去年')
_FORMAT_TOKENS = ('docx', 'xlsx', 'pdf', '简报', '文档', '表格', '邮件', '回执')
_RISK_TOKENS = ('原件', '删除', '覆盖', '登录', '密码', '账号',
                '网银', '付款', '上传', '下载', '提交', '脚本')
_QUANTITY = re.compile(r'[0-9零一二三四五六七八九十百两]+[份个页版条家张]')
_PLAN_CHANGING_HINTS = ('哪', '模板', '口径', '格式', '范围', '交付', '缺',
                        '对比', '份', '渠道', '对象', '无法', '未提供', '未指明')


def _found_in_order(text: str, tokens) -> tuple[str, ...]:
    hits = sorted(((text.find(token), token) for token in tokens if token in text),
                  key=lambda item: item[0])
    return tuple(token for _index, token in hits)


def preparse(text: str, known_names) -> ParsedSignals:
    """Extract deterministic signals from one turn of user text."""
    normalized = normalize_text(text)
    lowered = normalized.casefold()
    mentions = extract_explicit_references(normalized, known_names)
    return ParsedSignals(
        actions=_found_in_order(normalized, _ACTION_TOKENS),
        file_mentions=mentions,
        negated_mentions=tuple(sorted(negated_mentions(normalized, mentions))),
        quantities=tuple(dict.fromkeys(_QUANTITY.findall(normalized))),
        time_hints=_found_in_order(normalized, _TIME_TOKENS),
        conditions=_found_in_order(normalized, _CONDITION_TOKENS),
        deliverable_formats=_found_in_order(lowered, _FORMAT_TOKENS),
        cancellation=any(token in normalized for token in _CANCEL_TOKENS),
        authorization_claim=any(token in normalized for token in _AUTHORIZATION_TOKENS),
        risk_hints=_found_in_order(normalized, _RISK_TOKENS),
    )


def adjudicate(envelope, model, signals=None, *, allowed_capabilities=ALLOWED_CAPABILITIES,
               available_files=()) -> AdjudicatedIntent:
    """Bind a model intent to the frozen envelope; never invent scope."""
    envelope = TurnEnvelope.model_validate(envelope.model_dump())
    model = ModelIntent.model_validate(
        model.model_dump() if isinstance(model, ModelIntent) else model)
    selected = {item.id: item.name for item in envelope.selected_attachment_versions}
    selected_ids = set(selected)
    excluded_set = set(envelope.excluded_attachment_ids)
    by_name = {item['name']: item['id'] for item in available_files}
    by_name.update({name: identity for identity, name in selected.items()})
    if signals is None:
        signals = preparse(envelope.normalized_text, by_name.keys())
    else:
        signals = ParsedSignals.model_validate(
            signals.model_dump() if isinstance(signals, ParsedSignals) else signals)

    violations: list[str] = []
    questions: list[str] = []

    def resolve(items, role):
        resolved = []
        for item in items:
            identity = by_name.get(item)
            if identity is None or identity not in selected_ids:
                violations.append(f'模型给出了本轮范围外的{role}：{item}')
                continue
            if identity in excluded_set:
                violations.append(f'模型试图使用本轮已排除的文件：{selected[identity]}')
                continue
            resolved.append(identity)
        return tuple(dict.fromkeys(resolved))

    target_ids = resolve(model.targets, '目标')
    reference_ids = resolve(model.references, '参考')
    model_excluded = []
    for item in model.excluded_inputs:
        identity = by_name.get(item)
        if identity is None:
            violations.append(f'模型给出了未知的排除文件：{item}')
        elif identity in selected_ids:
            questions.append(f'模型要求排除“{item}”，但它仍在本轮勾选范围内，请确认。')
        else:
            model_excluded.append(identity)
    excluded_ids = tuple(sorted(excluded_set | set(model_excluded)))

    unique_caps = tuple(dict.fromkeys(model.required_capabilities))
    allowed = set(allowed_capabilities)
    capabilities = tuple(cap for cap in unique_caps if cap in allowed)
    dropped = tuple(cap for cap in unique_caps if cap not in allowed)
    risk_flags = tuple(dict.fromkeys((*model.risk_flags, *signals.risk_hints)))
    assumptions = list(model.assumptions)

    wants_execution = model.next_action in ('plan', 'browser') and model.intent == 'execute'
    if wants_execution:
        covered = set(target_ids) | set(reference_ids)
        for name in envelope.explicit_references:
            identity = by_name.get(name)
            if identity in selected_ids and identity not in covered:
                questions.append(f'本轮提到的“{name}”未被纳入处理范围，请确认是否需要处理。')
    kept_ambiguities = [item for item in model.ambiguities
                        if any(hint in item for hint in _PLAN_CHANGING_HINTS)
                        or any(name in item for name in by_name)]
    assumptions.extend(item for item in model.ambiguities
                       if item not in kept_ambiguities)

    if signals.cancellation or model.next_action == 'cancel' or model.intent == 'cancel':
        next_action = 'cancel'
        target_ids = reference_ids = ()
        capabilities = ()
        dropped = unique_caps
        questions = []
    elif model.next_action == 'answer' or model.intent == 'consult':
        next_action = 'answer'
        target_ids = reference_ids = ()
        dropped = unique_caps
        capabilities = ()
    elif model.next_action == 'refuse' or model.intent == 'unsupported':
        next_action = 'refuse'
        capabilities = ()
        dropped = unique_caps
    else:
        base = model.next_action if model.next_action in ('plan', 'browser') else 'plan'
        if model.next_action == 'ask' and kept_ambiguities:
            questions.extend(kept_ambiguities)
            next_action = 'ask'
            base = None
        # 不改变计划或成果的疑问不询问，按假设记录后继续
        if base is not None:
            if not capabilities or base == 'browser' and 'browser.task' not in capabilities:
                next_action = 'refuse'
            elif base == 'plan' and not target_ids \
                    and not set(capabilities) <= NO_TARGET_CAPABILITIES:
                questions.append('无法确定本轮处理对象，请确认要处理的文件后再发送。')
                next_action = 'ask'
            elif risk_flags:
                questions.append('本轮包含高风险操作（' + '、'.join(risk_flags)
                                 + '），请确认后再执行。')
                next_action = 'ask'
            elif questions:
                next_action = 'ask'
            else:
                next_action = base

    return AdjudicatedIntent(
        envelope_hash=envelope_hash(envelope), intent=model.intent, goal=model.goal,
        target_ids=target_ids, reference_ids=reference_ids, excluded_ids=excluded_ids,
        deliverables=model.deliverables, constraints=model.constraints,
        assumptions=tuple(assumptions), capabilities=capabilities,
        dropped_capabilities=dropped, scope_violations=tuple(violations),
        risk_flags=risk_flags, clarification_questions=tuple(questions),
        next_action=next_action)


def decision_fingerprint(decision: AdjudicatedIntent) -> str:
    decision = AdjudicatedIntent.model_validate(decision.model_dump())
    payload = json.dumps(decision.model_dump(), sort_keys=True, ensure_ascii=False,
                         allow_nan=False)
    return sha256(payload.encode('utf-8')).hexdigest()
