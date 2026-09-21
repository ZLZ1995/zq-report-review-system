import os

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import pytest


def make_store(tmp_path, owner='alice'):
    from asset_based_agent.technical_platform.store import PlatformStore
    return PlatformStore(tmp_path / 'state.sqlite', owner)


def add_file(store, project, tmp_path, name, content=b'data'):
    from asset_based_agent.technical_platform.skills import digest
    path = tmp_path / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return store.add_file(project, path, digest(path))


def make_gateway(store, mode='risk'):
    from asset_based_agent.technical_platform.input_gateway import InputGateway
    return InputGateway(store, lambda: mode)


def scaffold(tmp_path, files=('报告.docx', '明细表.xlsx'), owner='alice'):
    store = make_store(tmp_path, owner)
    project = store.create_project('p')
    session = store.create_session(project)
    ids = {name: add_file(store, project, tmp_path, name, name.encode()) for name in files}
    return store, project, session, ids


# --- turn_normalizer ---

def test_normalize_collapses_whitespace():
    from asset_based_agent.technical_platform.turn_normalizer import normalize_text
    assert normalize_text('  审核\n\n  这份   报告  ') == '审核 这份 报告'


def test_normalize_preserves_content_order():
    from asset_based_agent.technical_platform.turn_normalizer import normalize_text
    assert normalize_text('先审核，再生成') == '先审核，再生成'


def test_extract_mention_of_known_file():
    from asset_based_agent.technical_platform.turn_normalizer import (
        extract_explicit_references,
    )
    refs = extract_explicit_references('请审核 报告.docx 的内容', ['报告.docx', '明细表.xlsx'])
    assert refs == ('报告.docx',)


def test_extract_no_mention_returns_empty():
    from asset_based_agent.technical_platform.turn_normalizer import (
        extract_explicit_references,
    )
    assert extract_explicit_references('随便看看', ['报告.docx']) == ()


def test_extract_ignores_unknown_names():
    from asset_based_agent.technical_platform.turn_normalizer import (
        extract_explicit_references,
    )
    assert extract_explicit_references('审核 其他.docx', ['报告.docx']) == ()


def test_extract_matches_longest_name_first():
    from asset_based_agent.technical_platform.turn_normalizer import (
        extract_explicit_references,
    )
    refs = extract_explicit_references('用 明细表.xlsx', ['明细表.xlsx', '表.xlsx'])
    assert refs == ('明细表.xlsx',)


def test_extract_dedupes_repeated_mentions():
    from asset_based_agent.technical_platform.turn_normalizer import (
        extract_explicit_references,
    )
    refs = extract_explicit_references('审核 报告.docx 和 报告.docx', ['报告.docx'])
    assert refs == ('报告.docx',)


def test_extract_ascii_case_insensitive():
    from asset_based_agent.technical_platform.turn_normalizer import (
        extract_explicit_references,
    )
    refs = extract_explicit_references('review REPORT.DOCX', ['report.docx'])
    assert refs == ('report.docx',)


# --- TurnEnvelope model ---

def envelope_kwargs(ids):
    return {
        'owner': 'alice', 'project_id': 'p1', 'session_id': 's1', 'turn_id': 't1',
        'message_id': 'm1', 'raw_user_text': '审核', 'normalized_text': '审核',
        'explicit_references': (), 'selected_attachment_versions': ids,
        'newly_attached_ids': (), 'historical_reference_ids': (),
        'excluded_attachment_ids': (), 'active_model_id': 'model-a',
        'permission_mode': 'risk', 'browser_page_identity': None,
        'locale': 'zh-CN', 'timezone': 'Asia/Shanghai',
        'submitted_at': '2026-09-18T18:30:00+08:00',
        'prior_clarification_chain': (),
    }


def attachment(identity, name='报告.docx', sha='a' * 64):
    return {'id': identity, 'name': name, 'sha256': sha}


def test_valid_envelope_builds_and_is_frozen():
    from asset_based_agent.technical_platform.turn_context import TurnEnvelope
    env = TurnEnvelope(**envelope_kwargs((attachment('f1'),)))
    assert env.turn_id == 't1'
    with pytest.raises(ValueError):
        env.raw_user_text = 'changed'


def test_envelope_rejects_bad_schema_version():
    from asset_based_agent.technical_platform.turn_context import TurnEnvelope
    with pytest.raises(ValueError):
        TurnEnvelope(**{**envelope_kwargs(()), 'schema_version': 2})


def test_envelope_rejects_empty_owner():
    from asset_based_agent.technical_platform.turn_context import TurnEnvelope
    with pytest.raises(ValueError):
        TurnEnvelope(**{**envelope_kwargs(()), 'owner': ' '})


def test_envelope_rejects_empty_text():
    from asset_based_agent.technical_platform.turn_context import TurnEnvelope
    with pytest.raises(ValueError):
        TurnEnvelope(**{**envelope_kwargs(()), 'raw_user_text': '  '})


def test_envelope_rejects_duplicate_selected():
    from asset_based_agent.technical_platform.turn_context import TurnEnvelope
    with pytest.raises(ValueError):
        TurnEnvelope(**envelope_kwargs((attachment('f1'), attachment('f1'))))


def test_envelope_rejects_excluded_overlap_with_selected():
    from asset_based_agent.technical_platform.turn_context import TurnEnvelope
    with pytest.raises(ValueError):
        TurnEnvelope(**{**envelope_kwargs((attachment('f1'),)),
                        'excluded_attachment_ids': ('f1',)})


def test_envelope_rejects_historical_overlap_with_selected():
    from asset_based_agent.technical_platform.turn_context import TurnEnvelope
    with pytest.raises(ValueError):
        TurnEnvelope(**{**envelope_kwargs((attachment('f1'),)),
                        'historical_reference_ids': ('f1',)})


def test_envelope_rejects_newly_attached_outside_selected():
    from asset_based_agent.technical_platform.turn_context import TurnEnvelope
    with pytest.raises(ValueError):
        TurnEnvelope(**{**envelope_kwargs((attachment('f1'),)),
                        'newly_attached_ids': ('other',)})


def test_envelope_rejects_unknown_permission_mode():
    from asset_based_agent.technical_platform.turn_context import TurnEnvelope
    with pytest.raises(ValueError):
        TurnEnvelope(**{**envelope_kwargs(()), 'permission_mode': 'unlimited'})


def test_envelope_rejects_bad_timestamp():
    from asset_based_agent.technical_platform.turn_context import TurnEnvelope
    with pytest.raises(ValueError):
        TurnEnvelope(**{**envelope_kwargs(()), 'submitted_at': 'not-a-time'})


def test_envelope_hash_is_deterministic():
    from asset_based_agent.technical_platform.turn_context import (
        TurnEnvelope,
        envelope_hash,
    )
    first = TurnEnvelope(**envelope_kwargs((attachment('f1'),)))
    second = TurnEnvelope(**envelope_kwargs((attachment('f1'),)))
    assert envelope_hash(first) == envelope_hash(second)


def test_envelope_hash_changes_with_text():
    from asset_based_agent.technical_platform.turn_context import (
        TurnEnvelope,
        envelope_hash,
    )
    first = TurnEnvelope(**envelope_kwargs(()))
    changed = TurnEnvelope(**{**envelope_kwargs(()), 'raw_user_text': '生成'})
    assert envelope_hash(first) != envelope_hash(changed)


# --- turn_scope_policy ---

def test_scope_resolves_selected_files(tmp_path):
    store, _project, session, ids = scaffold(tmp_path)
    gateway = make_gateway(store)
    env = gateway.create(session, '审核这两个文件', selected_ids=list(ids.values()),
                         model_id='m')
    assert {item.id for item in env.selected_attachment_versions} == set(ids.values())


def test_scope_rejects_unknown_selected_id(tmp_path):
    store, _project, session, _ids = scaffold(tmp_path)
    gateway = make_gateway(store)
    with pytest.raises(PermissionError):
        gateway.create(session, '审核', selected_ids=['not-a-file'], model_id='m')


def test_scope_rejects_drifted_file_record(tmp_path):
    store, project, session, ids = scaffold(tmp_path)
    gateway = make_gateway(store)
    env = gateway.create(session, '审核', selected_ids=[ids['报告.docx']], model_id='m')
    add_file(store, project, tmp_path, '另一份.docx', b'new')
    # 篡改项目文件表：同名同 id 的记录哈希变化后必须拒绝
    with store.connect() as db:
        db.execute("UPDATE files SET sha256=? WHERE id=?", ('b' * 64, ids['报告.docx']))
    with pytest.raises(PermissionError):
        gateway.verify(env)


def test_mentioned_but_unselected_requires_clarification(tmp_path):
    from asset_based_agent.technical_platform.turn_scope_policy import (
        ScopeClarificationNeeded,
    )
    store, _project, session, ids = scaffold(tmp_path)
    gateway = make_gateway(store)
    with pytest.raises(ScopeClarificationNeeded) as exc:
        gateway.create(session, '请审核 报告.docx', selected_ids=[ids['明细表.xlsx']],
                       model_id='m')
    assert '报告.docx' in str(exc.value)


def test_mentioned_and_selected_passes(tmp_path):
    store, _project, session, ids = scaffold(tmp_path)
    gateway = make_gateway(store)
    env = gateway.create(session, '请审核 报告.docx 和 明细表.xlsx',
                         selected_ids=list(ids.values()), model_id='m')
    assert set(env.explicit_references) == {'报告.docx', '明细表.xlsx'}


def test_negated_unselected_file_is_excluded_without_clarification(tmp_path):
    store, _project, session, ids = scaffold(tmp_path)
    gateway = make_gateway(store)
    env = gateway.create(session, '审核 明细表.xlsx，不看 报告.docx',
                         selected_ids=[ids['明细表.xlsx']], model_id='m')
    assert env.excluded_attachment_ids == (ids['报告.docx'],)


def test_negated_selected_file_requires_clarification(tmp_path):
    from asset_based_agent.technical_platform.turn_scope_policy import (
        ScopeClarificationNeeded,
    )
    store, _project, session, ids = scaffold(tmp_path)
    gateway = make_gateway(store)
    with pytest.raises(ScopeClarificationNeeded):
        gateway.create(session, '全部审核，但不看 明细表.xlsx',
                       selected_ids=list(ids.values()), model_id='m')


def test_only_marker_with_extra_selection_requires_clarification(tmp_path):
    from asset_based_agent.technical_platform.turn_scope_policy import (
        ScopeClarificationNeeded,
    )
    store, _project, session, ids = scaffold(tmp_path)
    gateway = make_gateway(store)
    with pytest.raises(ScopeClarificationNeeded):
        gateway.create(session, '只审核 报告.docx',
                       selected_ids=list(ids.values()), model_id='m')


def test_only_marker_with_exact_selection_passes(tmp_path):
    store, _project, session, ids = scaffold(tmp_path)
    gateway = make_gateway(store)
    env = gateway.create(session, '只审核 报告.docx',
                         selected_ids=[ids['报告.docx']], model_id='m')
    assert [item.id for item in env.selected_attachment_versions] == [ids['报告.docx']]


def test_no_selection_no_mention_is_pure_consult(tmp_path):
    store, _project, session, ids = scaffold(tmp_path)
    gateway = make_gateway(store)
    env = gateway.create(session, '什么是资产评估？', selected_ids=[], model_id='m')
    assert env.selected_attachment_versions == ()
    assert set(env.historical_reference_ids) == set(ids.values())


def test_ambiguous_duplicate_name_requires_clarification(tmp_path):
    from asset_based_agent.technical_platform.turn_scope_policy import (
        ScopeClarificationNeeded,
    )
    store = make_store(tmp_path)
    project = store.create_project('p')
    session = store.create_session(project)
    first = add_file(store, project, tmp_path / 'a', '报告.docx', b'v1')
    second = add_file(store, project, tmp_path / 'b', '报告.docx', b'v2')
    gateway = make_gateway(store)
    with pytest.raises(ScopeClarificationNeeded):
        gateway.create(session, '审核 报告.docx', selected_ids=[first, second], model_id='m')


def test_same_name_different_version_is_distinct_attachment(tmp_path):
    store = make_store(tmp_path)
    project = store.create_project('p')
    session = store.create_session(project)
    first = add_file(store, project, tmp_path / 'a', '报告.docx', b'v1')
    second = add_file(store, project, tmp_path / 'b', '报告.docx', b'v2')
    gateway = make_gateway(store)
    env = gateway.create(session, '对比两份报告', selected_ids=[first, second], model_id='m')
    assert len({item.sha256 for item in env.selected_attachment_versions}) == 2


def test_historical_references_exclude_selected(tmp_path):
    store, _project, session, ids = scaffold(tmp_path, ('a.docx', 'b.docx', 'c.docx'))
    gateway = make_gateway(store)
    env = gateway.create(session, '审核', selected_ids=[ids['a.docx']], model_id='m')
    assert set(env.historical_reference_ids) == {ids['b.docx'], ids['c.docx']}


def test_newly_attached_must_be_subset_of_selected(tmp_path):
    store, _project, session, ids = scaffold(tmp_path)
    gateway = make_gateway(store)
    env = gateway.create(session, '审核', selected_ids=list(ids.values()),
                         newly_attached_ids=[ids['报告.docx']], model_id='m')
    assert env.newly_attached_ids == (ids['报告.docx'],)
    with pytest.raises(ValueError):
        gateway.create(session, '审核', selected_ids=[ids['报告.docx']],
                       newly_attached_ids=[ids['明细表.xlsx']], model_id='m')


def test_browser_page_identity_is_recorded(tmp_path):
    store, _project, session, _ids = scaffold(tmp_path)
    gateway = make_gateway(store)
    env = gateway.create(session, '看看网页', selected_ids=[], model_id='m',
                         browser_page_identity='tab-1:v3')
    assert env.browser_page_identity == 'tab-1:v3'


# --- input_gateway verify ---

def test_verify_accepts_unchanged_state(tmp_path):
    store, _project, session, ids = scaffold(tmp_path)
    gateway = make_gateway(store)
    env = gateway.create(session, '审核', selected_ids=[ids['报告.docx']], model_id='m')
    gateway.verify(env)


def test_verify_rejects_deleted_file(tmp_path):
    store, _project, session, ids = scaffold(tmp_path)
    gateway = make_gateway(store)
    env = gateway.create(session, '审核', selected_ids=[ids['报告.docx']], model_id='m')
    with store.connect() as db:
        db.execute('DELETE FROM files WHERE id=?', (ids['报告.docx'],))
    with pytest.raises(PermissionError):
        gateway.verify(env)


def test_verify_rejects_renamed_file(tmp_path):
    store, _project, session, ids = scaffold(tmp_path)
    gateway = make_gateway(store)
    env = gateway.create(session, '审核', selected_ids=[ids['报告.docx']], model_id='m')
    with store.connect() as db:
        db.execute("UPDATE files SET name='改名.docx' WHERE id=?", (ids['报告.docx'],))
    with pytest.raises(PermissionError):
        gateway.verify(env)


def test_verify_rejects_permission_mode_change(tmp_path):
    store, _project, session, ids = scaffold(tmp_path)
    mode = ['risk']
    from asset_based_agent.technical_platform.input_gateway import InputGateway
    gateway = InputGateway(store, lambda: mode[0])
    env = gateway.create(session, '审核', selected_ids=[ids['报告.docx']], model_id='m')
    mode[0] = 'full'
    with pytest.raises(PermissionError):
        gateway.verify(env)


def test_verify_rejects_foreign_owner(tmp_path):
    store, _project, session, ids = scaffold(tmp_path)
    gateway = make_gateway(store)
    env = gateway.create(session, '审核', selected_ids=[ids['报告.docx']], model_id='m')
    other = make_store(tmp_path, 'bob')
    from asset_based_agent.technical_platform.input_gateway import InputGateway
    with pytest.raises(PermissionError):
        InputGateway(other, lambda: 'risk').verify(env)


def test_verify_rejects_session_switch(tmp_path):
    store, _project, session, ids = scaffold(tmp_path)
    gateway = make_gateway(store)
    env = gateway.create(session, '审核', selected_ids=[ids['报告.docx']], model_id='m')
    drifted = env.model_copy(update={'session_id': 'other-session'})
    with pytest.raises((PermissionError, ValueError)):
        gateway.verify(drifted)


def test_understanding_request_maps_envelope(tmp_path):
    store, _project, session, ids = scaffold(tmp_path)
    gateway = make_gateway(store)
    env = gateway.create(session, '审核 报告.docx', selected_ids=[ids['报告.docx']],
                         model_id='m')
    request = gateway.understanding_request(env, skills=[], context=[])
    assert request.prompt == env.raw_user_text
    assert [f.id for f in request.files] == [ids['报告.docx']]
    assert request.model_id == 'm'


def test_late_understanding_result_rejected_after_file_change(tmp_path):
    from asset_based_agent.technical_platform.agent_controller import AgentController
    store, _project, session, ids = scaffold(tmp_path)
    gateway = make_gateway(store)
    env = gateway.create(session, '审核', selected_ids=[ids['报告.docx']], model_id='m')
    controller = AgentController(store)
    pending = controller.prepare(session, env.raw_user_text, model_id='m',
                                 selected_ids=[ids['报告.docx']], envelope=env)
    assert pending.envelope_hash is not None
    with store.connect() as db:
        db.execute("UPDATE files SET sha256=? WHERE id=?", ('c' * 64, ids['报告.docx']))
    payload = {
        'schema_version': 1, 'message_intent': 'consult', 'goal': '审核',
        'targets': [], 'references': [], 'excluded': [], 'constraints': [],
        'deliverables': [], 'missing_inputs': [],
        'evidence_message_ids': [pending.request.message_id], 'skill_ids': [],
        'next_action': 'answer', 'reply': '好的',
    }
    with pytest.raises(ValueError):
        controller.complete(pending, payload)


def test_prepare_without_envelope_keeps_legacy_path(tmp_path):
    from asset_based_agent.technical_platform.agent_controller import AgentController
    store, _project, session, ids = scaffold(tmp_path)
    controller = AgentController(store)
    pending = controller.prepare(session, '审核', model_id='m',
                                 selected_ids=[ids['报告.docx']])
    assert pending.envelope_hash is None


def test_scope_summary_lists_only_selected(tmp_path):
    from asset_based_agent.technical_platform.turn_scope_policy import (
        format_scope_summary,
    )
    store, _project, session, ids = scaffold(tmp_path)
    gateway = make_gateway(store)
    env = gateway.create(session, '审核', selected_ids=[ids['报告.docx']], model_id='m')
    summary = format_scope_summary(env)
    assert '报告.docx' in summary and '明细表.xlsx' not in summary


def test_envelope_does_not_carry_unselected_history(tmp_path):
    store, _project, session, ids = scaffold(tmp_path, ('a.docx', 'b.docx', 'c.docx'))
    gateway = make_gateway(store)
    env = gateway.create(session, '审核 a.docx', selected_ids=[ids['a.docx']], model_id='m')
    selected = {item.id for item in env.selected_attachment_versions}
    assert selected == {ids['a.docx']}
    assert selected.isdisjoint(env.historical_reference_ids)
    assert selected.isdisjoint(env.excluded_attachment_ids)


# --- UI integration ---

def window_fixture(tmp_path, monkeypatch=None):
    from PySide6.QtWidgets import QApplication

    from asset_based_agent.technical_platform.app import PlatformWindow
    from asset_based_agent.technical_platform.storage_preferences import (
        StoragePreferences,
    )
    qt = QApplication.instance() or QApplication([])
    program = tmp_path / 'program'
    program.mkdir(exist_ok=True)
    preferences = StoragePreferences(tmp_path / 'settings.sqlite', program)
    store = make_store(tmp_path)
    project = store.create_project('p')
    store.create_session(project)
    window = PlatformWindow(store, storage_preferences=preferences)
    window.reload_projects(project)
    return qt, window, store, project


def test_submit_blocks_when_mentioned_file_not_selected(tmp_path):
    _qt, window, store, project = window_fixture(tmp_path)
    try:
        add_file(store, project, tmp_path / 'f1', '报告.docx', b'1')
        add_file(store, project, tmp_path / 'f2', '明细表.xlsx', b'2')
        window.refresh_details(selected_ids={store.files(project)[1]['id']})
        window.composer.setPlainText('请审核 报告.docx')
        window.submit()
        assert '报告.docx' in window.status.text()
        assert window.worker is None
        assert window.composer.toPlainText() == '请审核 报告.docx'
    finally:
        window.close()


def test_submit_records_scope_summary_and_envelope(tmp_path):
    _qt, window, store, project = window_fixture(tmp_path)
    try:
        identity = add_file(store, project, tmp_path / 'f1', '报告.docx', b'1')
        window.refresh_details(selected_ids={identity})
        window.composer.setPlainText('请审核 报告.docx')
        window.connect_service = lambda: False
        window.submit()
        envelope = window.last_turn_envelope
        assert envelope is not None
        assert [item.id for item in envelope.selected_attachment_versions] == [identity]
        assert '报告.docx' in window.scope_summary_text()
    finally:
        window.close()
