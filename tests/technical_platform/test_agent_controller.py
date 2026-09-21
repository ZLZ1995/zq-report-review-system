import pytest

from asset_based_agent.technical_platform.store import PlatformStore


def response(request, *, ask=False):
    return {'schema_version': 1, 'message_intent': 'clarify' if ask else 'consult',
            'goal': '', 'targets': [], 'references': [], 'excluded': [], 'constraints': [],
            'deliverables': [], 'missing_inputs': [{'field': 'goal', 'question': '要审核还是生成？'}] if ask else [],
            'evidence_message_ids': [request.message_id], 'skill_ids': [],
            'next_action': 'ask' if ask else 'answer', 'reply': '要审核还是生成？' if ask else '审核默认只读。'}


def test_controller_allows_no_file_consultation_without_executing(tmp_path):
    from asset_based_agent.technical_platform.agent_controller import AgentController
    store = PlatformStore(tmp_path / 'db.sqlite', 'alice')
    session = store.create_session(store.create_project('one'))
    controller = AgentController(store)
    pending = controller.prepare(session, '解释审核', model_id='m', selected_ids=[])
    assert not pending.request.files
    review = next(s for s in pending.request.skills if s.id == 'report.review')
    assert '不修改原件' in review.description
    result = controller.complete(pending, response(pending.request))
    assert result.next_action == 'answer'
    assert [m['role'] for m in store.messages(session)] == ['user', 'assistant']
    assert store.messages(session)[-1]['text'] == '审核默认只读。'
    with pytest.raises(ValueError):
        controller.complete(pending, response(pending.request))


def test_clarification_survives_controller_recreation_and_cancellation(tmp_path):
    from asset_based_agent.technical_platform.agent_controller import AgentController
    store = PlatformStore(tmp_path / 'db.sqlite', 'alice')
    session = store.create_session(store.create_project('one'))
    controller = AgentController(store)
    first = controller.prepare(session, '帮我处理资料', model_id='m', selected_ids=[])
    controller.complete(first, response(first.request, ask=True))
    reopened = AgentController(store)
    second = reopened.prepare(session, '只是解释审核', model_id='m', selected_ids=[])
    assert [m.text for m in second.request.context] == ['帮我处理资料', '要审核还是生成？']
    reopened.cancel(second)
    with pytest.raises(ValueError):
        reopened.complete(second, response(second.request))
    third = reopened.prepare(session, '新的问题', model_id='m', selected_ids=[])
    assert third.request.context == []


def test_newer_request_invalidates_late_result(tmp_path):
    from asset_based_agent.technical_platform.agent_controller import AgentController
    store = PlatformStore(tmp_path / 'db.sqlite', 'alice')
    session = store.create_session(store.create_project('one'))
    controller = AgentController(store)
    first = controller.prepare(session, '第一问', model_id='m', selected_ids=[])
    controller.prepare(session, '第二问', model_id='m', selected_ids=[])
    with pytest.raises(ValueError):
        controller.complete(first, response(first.request))
    assert all(m['role'] == 'user' for m in store.messages(session))


def test_file_metadata_change_invalidates_result_without_reading_source(tmp_path):
    from asset_based_agent.technical_platform.agent_controller import AgentController
    from asset_based_agent.technical_platform.skills import digest
    store = PlatformStore(tmp_path / 'db.sqlite', 'alice')
    project = store.create_project('one')
    session = store.create_session(project)
    source = tmp_path / 'synthetic.txt'
    source.write_text('synthetic', encoding='utf-8')
    identity = store.add_file(project, source, digest(source))
    controller = AgentController(store)
    pending = controller.prepare(session, '解释资料', model_id='m', selected_ids=[identity])
    with store.connect() as db:
        db.execute('UPDATE files SET sha256=? WHERE id=?', ('0' * 64, identity))
    with pytest.raises(ValueError, match='变化'):
        controller.complete(pending, response(pending.request))
    assert source.read_text('utf-8') == 'synthetic'


def test_current_attachment_scope_never_expands_to_project_history(tmp_path):
    from asset_based_agent.technical_platform.agent_controller import AgentController
    from asset_based_agent.technical_platform.skills import digest

    store = PlatformStore(tmp_path / 'db.sqlite', 'alice')
    project = store.create_project('one')
    session = store.create_session(project)
    old = tmp_path / 'old.docx'; old.write_bytes(b'old')
    current = tmp_path / 'current.docx'; current.write_bytes(b'current')
    old_id = store.add_file(project, old, digest(old))
    current_id = store.add_file(project, current, digest(current))
    controller = AgentController(store)
    pending = controller.prepare(session, '只审核本轮上传的文件', model_id='m',
                                 selected_ids=[current_id])
    assert [item.id for item in pending.request.files] == [current_id]
    assert [item['id'] for item in pending.files] == [current_id]
    payload = {
        'schema_version': 1, 'message_intent': 'execute', 'goal': '审核本轮文件',
        'targets': [old_id], 'references': [], 'excluded': [], 'constraints': [],
        'deliverables': [], 'missing_inputs': [],
        'evidence_message_ids': [pending.request.message_id],
        'skill_ids': ['report.review'], 'next_action': 'plan', 'reply': '开始审核。',
    }
    with pytest.raises(ValueError, match='Unknown file reference'):
        controller.complete(pending, payload)
    assert store.runs(session) == []


def test_catalog_switch_does_not_redirect_pending_conversation(tmp_path):
    from asset_based_agent.technical_platform.agent_controller import AgentController
    from asset_based_agent.technical_platform.project_catalog import ProjectCatalog
    catalog = ProjectCatalog(tmp_path / 'index.sqlite', 'alice')
    roots = [tmp_path / name for name in ('one', 'two')]
    for root in roots:
        root.mkdir()
    project = catalog.create_project('one', roots[0])
    session = catalog.create_session(project)
    original = catalog.active
    controller = AgentController(catalog)
    pending = controller.prepare(session, '解释审核', model_id='m', selected_ids=[])
    catalog.create_project('two', roots[1])
    controller.complete(pending, response(pending.request))
    assert original.messages(session)[-1]['text'] == '审核默认只读。'


@pytest.mark.parametrize('long_field', ['prompt', 'reply'])
def test_clarification_preserves_full_requirements_including_tail(tmp_path, long_field):
    from asset_based_agent.technical_platform.agent_controller import AgentController
    store = PlatformStore(tmp_path / 'db.sqlite', 'alice')
    session = store.create_session(store.create_project('one'))
    controller = AgentController(store)
    full = '合成说明。' * 410 + '最后的限制：不得处理旧文件。'
    prompt = full if long_field == 'prompt' else '请帮我处理资料'
    first = controller.prepare(session, prompt, model_id='m', selected_ids=[])
    answer = response(first.request, ask=True)
    if long_field == 'reply':
        answer['reply'] = full
    controller.complete(first, answer)
    second = AgentController(store).prepare(session, '选择第一项', model_id='m', selected_ids=[])
    assert second.request.context[0].text == prompt
    assert second.request.context[1].text == answer['reply']


def test_clarification_overflow_does_not_silently_drop_original_constraints(tmp_path):
    from asset_based_agent.technical_platform.agent_controller import AgentController
    store = PlatformStore(tmp_path / 'db.sqlite', 'alice')
    session = store.create_session(store.create_project('one'))
    controller = AgentController(store)
    pending = controller.prepare(session, '禁止处理旧文件', model_id='m', selected_ids=[])
    for _ in range(8):
        controller.complete(pending, response(pending.request, ask=True))
        pending = controller.prepare(session, '继续澄清', model_id='m', selected_ids=[])
    # 新契约（压缩接线后）：超界先压缩而非立即拒绝，但原始限制绝不静默丢失——
    # 它必须逐字存在于会话存储，且在压缩摘要中以可回查形式保留。
    assert store.messages(session)[0]['text'] == '禁止处理旧文件'
    texts = [m.text for m in pending.request.context]
    assert any('禁止处理旧文件' in text for text in texts)
    summary = next((m for m in pending.request.context
                    if m.id.startswith('sum-')), None)
    assert summary is not None
    assert '非原始证据' in summary.text
