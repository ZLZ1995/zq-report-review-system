"""S10：ReferenceResolver——验收语料的确定性指代解析。"""
from asset_based_agent.technical_platform.agent_core.reference_resolver import (
    resolve_references,
)

BINDINGS = [
    {'file_id': 'file-first', 'binding_kind': 'explicit_upload'},
    {'file_id': 'file-second', 'binding_kind': 'explicit_upload'},
    {'file_id': 'file-third', 'binding_kind': 'explicit_upload'},
]


def test_plain_continuation_means_continue_last_work():
    outcome = resolve_references('继续', bindings=[], entries=[])
    assert outcome['continuation'] is True
    assert outcome['file_ids'] == []


def test_recent_file_pronoun_resolves_to_latest_binding():
    outcome = resolve_references('刚才那个文件再检查一遍',
                                 bindings=BINDINGS, entries=[])
    assert outcome['file_ids'] == ['file-third']


def test_it_pronoun_with_upload_action():
    outcome = resolve_references('把它上传 OA', bindings=BINDINGS, entries=[])
    assert outcome['file_ids'] == ['file-third']
    assert 'external_upload' in outcome['action_hints']


def test_only_newly_uploaded_two_files_selects_latest_two():
    outcome = resolve_references('只审核新上传的两个文件',
                                 bindings=BINDINGS, entries=[])
    assert outcome['file_ids'] == ['file-second', 'file-third']
    assert 'review' in outcome['action_hints']


def test_last_caliber_with_period_override():
    outcome = resolve_references('用上次的口径，但期间改为 2026 年 7 月',
                                 bindings=BINDINGS, entries=[])
    assert outcome['used_last_facts'] is True
    assert outcome['overrides'] == {'期间': '2026年7月'}


def test_no_reference_returns_empty_resolution():
    outcome = resolve_references('帮我写一份全新的说明',
                                 bindings=BINDINGS, entries=[])
    assert outcome['continuation'] is False
    assert outcome['file_ids'] == []
    assert outcome['overrides'] == {}
