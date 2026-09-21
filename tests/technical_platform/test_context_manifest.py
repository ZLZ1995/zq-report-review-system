"""G03：Context Manifest、证据检索和预算。

验收：同一输入生成稳定 manifest；隐藏表片段进入 manifest 为 0；本轮范围和
业务红线永不被裁剪；长会话 Token 显著下降；诊断视图不泄露系统提示词、
价格、Token 或密钥。
"""
import pytest


def make_envelope():
    from asset_based_agent.technical_platform.turn_scope_policy import resolve_scope
    files = [{'id': 'f1', 'name': '审核报告.docx', 'sha256': 'a' * 64},
             {'id': 'f2', 'name': '明细表.xlsx', 'sha256': 'b' * 64}]
    return resolve_scope(
        owner='alice', project_id='p1', session_id='s1',
        raw_user_text='审审核报告.docx，参考明细表.xlsx', selected_ids=['f1', 'f2'],
        available_files=files, active_model_id='model-a', permission_mode='risk',
        clock=None)


def fragment(identity, file_id='f1', name='审核报告.docx', role='target',
             visibility='visible', text='片段正文'):
    return {'id': identity, 'file_id': file_id, 'file_name': name, 'role': role,
            'sheet_visibility': visibility, 'text': text}


# --- context_budget ---

def test_token_estimate_counts_cjk_heavier_than_ascii():
    from asset_based_agent.technical_platform.context_budget import estimate_tokens
    assert estimate_tokens('审核报告') > estimate_tokens('abcd')
    assert estimate_tokens('') == 0


def test_token_estimate_is_deterministic_and_monotonic():
    from asset_based_agent.technical_platform.context_budget import estimate_tokens
    assert estimate_tokens('审核报告') == estimate_tokens('审核报告')
    assert estimate_tokens('审核报告审核报告') >= estimate_tokens('审核报告')


def test_budget_plan_never_trims_pinned_sections():
    from asset_based_agent.technical_platform.context_budget import plan_budget
    sections = {'redlines': {'tokens': 500, 'pinned': True},
                'scope': {'tokens': 300, 'pinned': True},
                'evidence': {'tokens': 5000, 'pinned': False},
                'memories': {'tokens': 800, 'pinned': False}}
    plan = plan_budget(sections, total=2000)
    assert plan['redlines'] == 500 and plan['scope'] == 300
    assert sum(plan.values()) <= 2000


def test_budget_plan_trims_unpinned_to_zero_when_needed():
    from asset_based_agent.technical_platform.context_budget import plan_budget
    sections = {'redlines': {'tokens': 1500, 'pinned': True},
                'evidence': {'tokens': 9000, 'pinned': False}}
    plan = plan_budget(sections, total=1500)
    assert plan['redlines'] == 1500 and plan['evidence'] == 0


def test_budget_plan_rejects_unknown_section():
    from asset_based_agent.technical_platform.context_budget import plan_budget
    with pytest.raises(ValueError):
        plan_budget({'mystery': {'tokens': 1, 'pinned': False}}, total=10)


def test_trim_items_keeps_order_and_budget():
    from asset_based_agent.technical_platform.context_budget import trim_to_budget
    items = [('a', '审核报告片段'), ('b', '第二段内容'), ('c', '第三段内容')]
    full = trim_to_budget(items, budget=10 ** 6)
    assert [i for i, _t in full] == ['a', 'b', 'c']
    tight = trim_to_budget(items, budget=1)
    assert len(tight) < 3


# --- evidence_retriever ---

def test_retrieve_orders_targets_before_references():
    from asset_based_agent.technical_platform.evidence_retriever import (
        retrieve_evidence,
    )
    fragments = [fragment('e1', role='reference', file_id='f2', name='明细表.xlsx'),
                 fragment('e2', role='target')]
    result = retrieve_evidence(fragments, budget=10 ** 6)
    assert [item.id for item in result.fragments] == ['e2', 'e1']


def test_retrieve_filters_hidden_and_very_hidden_sheets():
    from asset_based_agent.technical_platform.evidence_retriever import (
        retrieve_evidence,
    )
    fragments = [fragment('e1'), fragment('e2', visibility='hidden'),
                 fragment('e3', visibility='veryHidden')]
    result = retrieve_evidence(fragments, budget=10 ** 6)
    assert [item.id for item in result.fragments] == ['e1']
    assert sorted(result.dropped_hidden) == ['e2', 'e3']


def test_retrieve_rejects_unknown_role():
    from asset_based_agent.technical_platform.evidence_retriever import (
        retrieve_evidence,
    )
    with pytest.raises(ValueError):
        retrieve_evidence([fragment('e1', role='boss')], budget=100)


def test_retrieve_respects_budget_and_reports_dropped():
    from asset_based_agent.technical_platform.evidence_retriever import (
        retrieve_evidence,
    )
    fragments = [fragment(f'e{i}', text='正文' * 50) for i in range(10)]
    result = retrieve_evidence(fragments, budget=10)
    assert len(result.fragments) < 10 and result.dropped_budget


# --- conversation_compactor ---

def messages(count):
    return [{'id': f'm{i}', 'role': 'user', 'text': f'第{i}轮要求'}
            for i in range(1, count + 1)]


def test_compact_marks_summary_as_non_original_evidence():
    from asset_based_agent.technical_platform.conversation_compactor import (
        compact_messages,
    )
    result = compact_messages(messages(9), keep_recent=2)
    summaries = [item for item in result if item['kind'] == 'summary']
    assert summaries and summaries[0]['non_original_evidence'] is True
    kept = [item for item in result if item['kind'] == 'message']
    assert [item['id'] for item in kept] == ['m8', 'm9']


def test_compact_summary_preserves_source_ids_for_lookback():
    from asset_based_agent.technical_platform.conversation_compactor import (
        compact_messages,
        summary_source_ids,
    )
    result = compact_messages(messages(9), keep_recent=2)
    summary = next(item for item in result if item['kind'] == 'summary')
    assert summary_source_ids(summary) == [f'm{i}' for i in range(1, 8)]


def test_compact_short_history_is_noop():
    from asset_based_agent.technical_platform.conversation_compactor import (
        compact_messages,
    )
    original = messages(2)
    assert compact_messages(original, keep_recent=6) == [
        {'kind': 'message', **item} for item in original]


def test_compact_rejects_overlapping_ids():
    from asset_based_agent.technical_platform.conversation_compactor import (
        compact_messages,
    )
    with pytest.raises(ValueError):
        compact_messages([{'id': 'm1', 'role': 'user', 'text': 'x'},
                          {'id': 'm1', 'role': 'user', 'text': 'y'}], keep_recent=1)


# --- context_manifest ---

def manifest_kwargs(**overrides):
    envelope = make_envelope()
    kwargs = {
        'envelope': envelope,
        'system_policy_hash': 'c' * 64,
        'skills': [{'id': 'report.review', 'version': '1.2.0', 'rules_sha256': 'd' * 64}],
        'memories': [{'id': f'mem{i}', 'text': f'偏好{i}'} for i in range(1, 8)],
        'summaries': [{'id': 'sum1', 'source_message_ids': ['m1', 'm2']}],
        'evidence': [fragment('e1'), fragment('e2', role='reference',
                                              file_id='f2', name='明细表.xlsx')],
        'tool_receipt_ids': ['rc1'],
        'total_budget': 6000,
    }
    kwargs.update(overrides)
    return kwargs


def test_manifest_is_stable_for_same_input():
    from asset_based_agent.technical_platform.context_manifest import build_manifest
    kwargs = manifest_kwargs()
    first = build_manifest(**kwargs)
    second = build_manifest(**kwargs)
    assert first.manifest_id == second.manifest_id
    assert first.model_dump() == second.model_dump()


def test_manifest_records_provenance_and_budgets():
    from asset_based_agent.technical_platform.context_manifest import build_manifest
    from asset_based_agent.technical_platform.turn_context import envelope_hash
    kwargs = manifest_kwargs()
    manifest = build_manifest(**kwargs)
    assert manifest.envelope_hash == envelope_hash(kwargs['envelope'])
    assert manifest.system_policy_hash == 'c' * 64
    assert manifest.skill_pins == (('report.review', '1.2.0', 'd' * 64),)
    assert manifest.tool_receipt_ids == ('rc1',)
    assert sum(manifest.budgets.values()) <= 6000


def test_manifest_keeps_at_most_five_memories():
    from asset_based_agent.technical_platform.context_manifest import build_manifest
    manifest = build_manifest(**manifest_kwargs())
    assert len(manifest.memory_ids) == 5


def test_manifest_marks_summaries_non_original():
    from asset_based_agent.technical_platform.context_manifest import build_manifest
    manifest = build_manifest(**manifest_kwargs())
    assert manifest.summary_ids == ('sum1',)
    assert manifest.summaries_non_original is True


def test_manifest_rejects_hidden_sheet_evidence():
    from asset_based_agent.technical_platform.context_manifest import build_manifest
    with pytest.raises(ValueError):
        build_manifest(**manifest_kwargs(
            evidence=[fragment('e1', visibility='veryHidden')]))


def test_manifest_rejects_evidence_outside_envelope():
    from asset_based_agent.technical_platform.context_manifest import build_manifest
    with pytest.raises(ValueError):
        build_manifest(**manifest_kwargs(
            evidence=[fragment('e9', file_id='f99', name='别的.docx')]))


def test_manifest_redlines_and_scope_never_trimmed():
    from asset_based_agent.technical_platform.context_manifest import build_manifest
    manifest = build_manifest(**manifest_kwargs(total_budget=400))
    assert manifest.budgets['redlines'] > 0 and manifest.budgets['scope'] > 0
    assert manifest.budgets['evidence'] == 0


def test_diagnostics_view_hides_prompts_prices_tokens_and_keys():
    from asset_based_agent.technical_platform.context_manifest import (
        build_manifest,
        diagnostics_view,
    )
    view = diagnostics_view(build_manifest(**manifest_kwargs()))
    rendered = str(view).casefold()
    for forbidden in ('token', 'price', '价格', '费用', 'sha256', 'secret', 'api'):
        assert forbidden not in rendered
    assert view['sources']['evidence_fragments'] == 2
    assert view['sources']['memories'] == 5
    assert view['sources']['skills'] == ['report.review']


def test_manifest_compacted_session_uses_fewer_tokens():
    from asset_based_agent.technical_platform.context_budget import estimate_tokens
    from asset_based_agent.technical_platform.context_manifest import build_manifest
    from asset_based_agent.technical_platform.conversation_compactor import (
        compact_messages,
    )
    long_history = [{'id': f'm{i}', 'role': 'user', 'text': f'第{i}轮要求' * 80}
                    for i in range(1, 21)]
    compacted = compact_messages(long_history, keep_recent=2)
    summaries = [{'id': item['id'], 'source_message_ids': item['source_message_ids']}
                 for item in compacted if item['kind'] == 'summary']
    raw_tokens = sum(estimate_tokens(m['text']) for m in long_history)
    kwargs = manifest_kwargs(summaries=summaries)
    manifest = build_manifest(**kwargs)
    assert manifest.budgets['history'] < raw_tokens
