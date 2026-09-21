"""G02 自然语言理解 v2：确定性预解析 + 严格模型意图 + 本地裁决。

评估集驱动的验收：目标/参考/排除文件准确率 100%，高风险动作漏澄清 0，
错误 Skill 实际执行 0，不必要澄清率低于 10%，模型不可授予工具权限。
"""
import json
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path

import pytest

FIXTURE = Path(__file__).parent / 'fixtures' / 'intent_eval_zh.jsonl'
ALLOWED = ('report.review', 'review.preflight', 'valuation-detail-workbook-fill',
           'gongshang-change-history-docx', 'financial-brief-docx',
           'office-workflow-to-skill', 'browser.task')

CLOCK = lambda: datetime(2026, 9, 18, 18, 30, tzinfo=timezone.utc)


def load_eval():
    with FIXTURE.open(encoding='utf-8') as fh:
        return [json.loads(line) for line in fh if line.strip()]


def make_envelope(entry):
    from asset_based_agent.technical_platform.turn_scope_policy import (
        ScopeClarificationNeeded,
        resolve_scope,
    )
    files = [{'id': f'f{index}', 'name': name,
              'sha256': sha256(name.encode('utf-8')).hexdigest()}
             for index, name in enumerate(entry['files'], 1)]
    by_name = {item['name']: item for item in files}
    try:
        envelope = resolve_scope(
            owner='alice', project_id='p1', session_id='s1',
            raw_user_text=entry['text'],
            selected_ids=[by_name[name]['id'] for name in entry['sel']],
            available_files=files, active_model_id='model-a',
            permission_mode='risk', clock=CLOCK)
    except ScopeClarificationNeeded:
        return None, files
    return envelope, files


def make_model_intent(entry):
    from asset_based_agent.technical_platform.intent_schema import ModelIntent
    spec = entry['model']
    return ModelIntent(
        intent=spec['intent'], goal=spec['goal'], targets=tuple(spec['targets']),
        references=tuple(spec['references']), excluded_inputs=tuple(spec['excluded']),
        deliverables=tuple(spec['deliverables']), constraints=tuple(spec['constraints']),
        assumptions=tuple(spec['assumptions']),
        required_capabilities=tuple(spec['capabilities']),
        risk_flags=tuple(spec['risk']), ambiguities=tuple(spec['amb']),
        next_action=spec['next'])


def run_pipeline(entry):
    """完整本地链路：范围解析 → 预解析 → 模型结构化输出（夹具）→ 本地裁决。"""
    from asset_based_agent.technical_platform.intent_policy import adjudicate, preparse
    envelope, files = make_envelope(entry)
    if envelope is None:
        return {'clarified': True, 'next': 'ask', 'targets': [], 'references': [],
                'excluded': [], 'capabilities': [], 'risk_flags': []}
    names = {item['id']: item['name'] for item in files}
    signals = preparse(envelope.normalized_text, names.values())
    decision = adjudicate(envelope, make_model_intent(entry), signals,
                          allowed_capabilities=ALLOWED)
    return {
        'clarified': decision.next_action == 'ask',
        'next': decision.next_action,
        'targets': [names[i] for i in decision.target_ids],
        'references': [names[i] for i in decision.reference_ids],
        'excluded': [names[i] for i in decision.excluded_ids],
        'capabilities': list(decision.capabilities),
        'risk_flags': list(decision.risk_flags),
    }


# --- intent_schema ---

def test_model_intent_rejects_tool_grant_fields():
    from asset_based_agent.technical_platform.intent_schema import ModelIntent
    with pytest.raises(ValueError):
        ModelIntent(intent='execute', goal='x', granted_tools=['shell'])


def test_model_intent_rejects_unknown_next_action():
    from asset_based_agent.technical_platform.intent_schema import ModelIntent
    with pytest.raises(ValueError):
        ModelIntent(intent='execute', goal='x', next_action='grant_permission')


def test_model_intent_rejects_unknown_intent():
    from asset_based_agent.technical_platform.intent_schema import ModelIntent
    with pytest.raises(ValueError):
        ModelIntent(intent='hack', goal='x')


def test_model_intent_defaults_are_empty_and_frozen():
    from asset_based_agent.technical_platform.intent_schema import ModelIntent
    intent = ModelIntent(intent='consult', goal='问个问题', next_action='answer')
    assert intent.targets == () and intent.required_capabilities == ()
    with pytest.raises(ValueError):
        intent.goal = '改'


# --- preparse ---

def test_preparse_detects_mentions_and_negation():
    from asset_based_agent.technical_platform.intent_policy import preparse
    signals = preparse('审审核报告.docx，不看明细表.xlsx', ['审核报告.docx', '明细表.xlsx'])
    assert signals.file_mentions == ('审核报告.docx', '明细表.xlsx')
    assert signals.negated_mentions == ('明细表.xlsx',)


def test_preparse_detects_cancellation():
    from asset_based_agent.technical_platform.intent_policy import preparse
    assert preparse('算了，别做了', []).cancellation is True
    assert preparse('审一下审核报告.docx', ['审核报告.docx']).cancellation is False


def test_preparse_detects_risk_hints():
    from asset_based_agent.technical_platform.intent_policy import preparse
    signals = preparse('登录OA把审核报告.docx上传，顺便下载回执', ['审核报告.docx'])
    assert '登录' in signals.risk_hints
    assert '上传' in signals.risk_hints
    assert '下载' in signals.risk_hints


def test_preparse_detects_original_modification_risk():
    from asset_based_agent.technical_platform.intent_policy import preparse
    assert '原件' in preparse('直接改原件吧', []).risk_hints


def test_preparse_detects_conditions_quantities_time_and_format():
    from asset_based_agent.technical_platform.intent_policy import preparse
    signals = preparse('如果明细表.xlsx超过五十页，先出一份docx简报', ['明细表.xlsx'])
    assert signals.conditions
    assert signals.quantities
    assert 'docx' in signals.deliverable_formats
    assert preparse('用上周的数据', []).time_hints


def test_preparse_is_deterministic():
    from asset_based_agent.technical_platform.intent_policy import preparse
    text = '先审审核报告.docx，如果没问题再出简报'
    assert preparse(text, ['审核报告.docx']) == preparse(text, ['审核报告.docx'])


# --- adjudicate ---

def adjudication_fixture(tmp_path, text='审审核报告.docx，参考明细表.xlsx',
                         selected=('审核报告.docx', '明细表.xlsx'), **model_overrides):
    from asset_based_agent.technical_platform.intent_policy import adjudicate, preparse
    from asset_based_agent.technical_platform.intent_schema import ModelIntent
    from asset_based_agent.technical_platform.turn_scope_policy import resolve_scope
    files = [{'id': f'f{index}', 'name': name,
              'sha256': sha256(name.encode('utf-8')).hexdigest()}
             for index, name in enumerate(
                 ['审核报告.docx', '明细表.xlsx', '旧底稿.docx'], 1)]
    by_name = {item['name']: item for item in files}
    envelope = resolve_scope(
        owner='alice', project_id='p1', session_id='s1', raw_user_text=text,
        selected_ids=[by_name[name]['id'] for name in selected],
        available_files=files, active_model_id='model-a',
        permission_mode='risk', clock=CLOCK)
    spec = {'intent': 'execute', 'goal': '审核', 'targets': ['审核报告.docx'],
            'references': ['明细表.xlsx'], 'excluded': [], 'deliverables': ['意见'],
            'constraints': [], 'assumptions': [], 'capabilities': ['report.review'],
            'risk': [], 'amb': [], 'next': 'plan'}
    spec.update(model_overrides)
    model = ModelIntent(
        intent=spec['intent'], goal=spec['goal'], targets=tuple(spec['targets']),
        references=tuple(spec['references']), excluded_inputs=tuple(spec['excluded'],
        ), deliverables=tuple(spec['deliverables']),
        constraints=tuple(spec['constraints']), assumptions=tuple(spec['assumptions']),
        required_capabilities=tuple(spec['capabilities']),
        risk_flags=tuple(spec['risk']), ambiguities=tuple(spec['amb']),
        next_action=spec['next'])
    signals = preparse(envelope.normalized_text, by_name.keys())
    decision = adjudicate(envelope, model, signals, allowed_capabilities=ALLOWED)
    return envelope, by_name, decision


def test_adjudicate_maps_names_to_envelope_ids(tmp_path):
    _envelope, by_name, decision = adjudication_fixture(tmp_path)
    assert decision.next_action == 'plan'
    assert decision.target_ids == (by_name['审核报告.docx']['id'],)
    assert decision.reference_ids == (by_name['明细表.xlsx']['id'],)


def test_adjudicate_rejects_envelope_foreign_id(tmp_path):
    _e, _b, decision = adjudication_fixture(tmp_path, targets=['f99'])
    assert decision.next_action == 'ask'
    assert decision.scope_violations


def test_adjudicate_strips_historical_file_injection(tmp_path):
    _e, by_name, decision = adjudication_fixture(
        tmp_path, targets=['审核报告.docx', '旧底稿.docx'])
    assert by_name['旧底稿.docx']['id'] not in decision.target_ids
    assert decision.scope_violations


def test_adjudicate_clarifies_uncovered_mention(tmp_path):
    _e, _b, decision = adjudication_fixture(tmp_path, references=[])
    assert decision.next_action == 'ask'
    assert any('明细表.xlsx' in q for q in decision.clarification_questions)


def test_adjudicate_drops_unknown_capability_and_refuses(tmp_path):
    _e, _b, decision = adjudication_fixture(tmp_path, capabilities=['shell.exec'])
    assert decision.next_action == 'refuse'
    assert decision.capabilities == ()
    assert decision.dropped_capabilities == ('shell.exec',)


def test_adjudicate_keeps_whitelisted_capabilities_sorted(tmp_path):
    _e, _b, decision = adjudication_fixture(
        tmp_path, capabilities=['report.review', 'financial-brief-docx'])
    assert set(decision.capabilities) == {'report.review', 'financial-brief-docx'}


def test_adjudicate_risk_downgrades_plan_to_ask(tmp_path):
    _e, _b, decision = adjudication_fixture(tmp_path, risk=['upload'])
    assert decision.next_action == 'ask'
    assert 'upload' in decision.risk_flags


def test_adjudicate_preparse_risk_hint_downgrades(tmp_path):
    _e, _b, decision = adjudication_fixture(tmp_path, text='审完审核报告.docx上传到OA',
                                            references=[])
    assert decision.next_action == 'ask'
    assert '上传' in decision.risk_flags


def test_adjudicate_cancel_takes_precedence(tmp_path):
    _e, _b, decision = adjudication_fixture(tmp_path, text='算了，别做了',
                                            intent='cancel', targets=[], references=[],
                                            capabilities=[], next='cancel')
    assert decision.next_action == 'cancel'
    assert decision.target_ids == ()


def test_adjudicate_consult_answer_drops_capabilities(tmp_path):
    _e, _b, decision = adjudication_fixture(
        tmp_path, intent='consult', targets=[], references=[],
        capabilities=['report.review'], next='answer')
    assert decision.next_action == 'answer'
    assert decision.capabilities == ()


def test_adjudicate_plan_without_targets_requires_clarification(tmp_path):
    _e, _b, decision = adjudication_fixture(tmp_path, targets=[], references=[])
    assert decision.next_action == 'ask'


def test_adjudicate_no_target_capability_allows_empty_targets(tmp_path):
    _e, _b, decision = adjudication_fixture(
        tmp_path, text='把刚才的办公流程做成skill', targets=[], references=[],
        capabilities=['office-workflow-to-skill'])
    assert decision.next_action == 'plan'


def test_adjudicate_filters_non_plan_changing_ambiguity(tmp_path):
    _e, _b, decision = adjudication_fixture(
        tmp_path, amb=['要不要写得更详细一点'], next='ask')
    assert decision.next_action == 'plan'
    assert '要不要写得更详细一点' in decision.assumptions


def test_adjudicate_keeps_plan_changing_ambiguity(tmp_path):
    _e, _b, decision = adjudication_fixture(
        tmp_path, amb=['缺少对比所需的第二份文件'], next='ask')
    assert decision.next_action == 'ask'
    assert any('缺' in q for q in decision.clarification_questions)


def test_adjudicate_is_deterministic(tmp_path):
    from asset_based_agent.technical_platform.intent_policy import decision_fingerprint
    _e1, _b1, first = adjudication_fixture(tmp_path)
    _e2, _b2, second = adjudication_fixture(tmp_path)
    # 每轮信封有独立 turn/message 身份，哈希必然不同；裁决内容必须一致
    assert (first.model_dump(exclude={'envelope_hash'})
            == second.model_dump(exclude={'envelope_hash'}))
    assert decision_fingerprint(first) != decision_fingerprint(second)


def test_adjudicate_records_envelope_hash(tmp_path):
    from asset_based_agent.technical_platform.turn_context import envelope_hash
    envelope, _b, decision = adjudication_fixture(tmp_path)
    assert decision.envelope_hash == envelope_hash(envelope)


# --- 评估集 ---

def test_eval_fixture_size_and_categories():
    entries = load_eval()
    assert len(entries) >= 120
    required = {'口语', '错别字', '省略', '连续要求', '否定', '双重否定', '条件句',
                '跨Skill', '用户纠正', '资料不全', '浏览器组合', 'Skill ZIP', '纯问答'}
    assert required <= {entry['cat'] for entry in entries}
    ids = [entry['id'] for entry in entries]
    assert len(set(ids)) == len(ids)


def test_eval_model_outputs_conform_to_schema():
    for entry in load_eval():
        if entry['model'] is not None:
            make_model_intent(entry)


def test_eval_scope_accuracy_is_total():
    failures = []
    for entry in load_eval():
        outcome = run_pipeline(entry)
        if outcome['next'] == 'ask':
            continue
        for key, field in (('t', 'targets'), ('r', 'references'), ('x', 'excluded')):
            if sorted(outcome[field]) != sorted(entry['exp'][key]):
                failures.append(f"{entry['id']}: {field} {outcome[field]} != {entry['exp'][key]}")
    assert not failures, '; '.join(failures)


def test_eval_high_risk_never_executes_without_clarification():
    for entry in load_eval():
        if not entry['exp']['hr']:
            continue
        outcome = run_pipeline(entry)
        assert outcome['next'] in ('ask', 'refuse'), entry['id']
        assert outcome['risk_flags'], entry['id']


def test_eval_no_capability_outside_whitelist_executes():
    for entry in load_eval():
        outcome = run_pipeline(entry)
        if outcome['next'] in ('plan', 'browser'):
            assert set(outcome['capabilities']) <= set(ALLOWED), entry['id']


def test_eval_unnecessary_clarification_rate_below_ten_percent():
    entries = load_eval()
    unnecessary = [entry['id'] for entry in entries
                   if run_pipeline(entry)['clarified'] and not entry['exp']['c']]
    assert len(unnecessary) / len(entries) < 0.10, unnecessary


def test_eval_necessary_clarification_not_missed():
    missed = [entry['id'] for entry in load_eval()
              if entry['exp']['c'] and not run_pipeline(entry)['clarified']
              and run_pipeline(entry)['next'] != 'refuse']
    assert not missed, missed
