import json

import pytest
from test_agent_controller import response
from test_export import case

from asset_based_agent.technical_platform.agent_controller import AgentController
from asset_based_agent.technical_platform.session_service import SessionService


def branched(tmp_path):
    store, run = case(tmp_path)
    parent = store.run(run)['session']
    result = json.loads(store.run(run)['result'])
    result['internal_path'] = 'D:/private/not-for-model'
    result['authorization'] = 'SECRET-GRANT'
    store.save_result(run, result)
    store.append(parent, 'assistant', 'completed review')
    child = SessionService(store).fork(parent, store.messages(parent)[-1]['id'], 'child')
    return store, child, run


def test_branch_understanding_receives_completed_findings_not_scope_or_authority(tmp_path):
    store, child, run = branched(tmp_path)
    controller = AgentController(store)
    pending = controller.prepare(child, '解释上一轮问题', model_id='m', selected_ids=[])
    assert len(pending.request.context) == 1
    text = pending.request.context[0].text
    assert 'Evidence mismatch' in text and run in text
    assert '不代表业务结论已核实' in text
    assert 'SECRET-GRANT' not in text and 'D:/private' not in text
    assert not pending.request.files
    assert store.runs(child) == []
    controller.complete(pending, response(pending.request))


def test_branch_reference_is_revalidated_before_accepting_model_reply(tmp_path):
    store, child, run = branched(tmp_path)
    controller = AgentController(store)
    pending = controller.prepare(child, '解释上一轮问题', model_id='m', selected_ids=[])
    store.save_result(run, {'kind': 'review', 'issues': []})
    with pytest.raises(ValueError):
        controller.complete(pending, response(pending.request))
    assert [m['role'] for m in store.messages(child)] == ['user']


def test_branch_clarification_keeps_reference_once_and_can_be_cancelled(tmp_path):
    store, child, _ = branched(tmp_path)
    controller = AgentController(store)
    first = controller.prepare(child, '继续', model_id='m', selected_ids=[])
    controller.complete(first, response(first.request, ask=True))
    second = AgentController(store).prepare(child, '仅解释', model_id='m', selected_ids=[])
    assert len(second.request.context) == 3
    assert second.request.context[0] == first.request.context[0]
    controller.cancel(second)


def test_oversized_branch_context_rejected_before_conversation_mutation(tmp_path):
    store, run = case(tmp_path)
    parent = store.run(run)['session']
    result = json.loads(store.run(run)['result'])
    result['issues'][0]['description'] = 'synthetic finding ' * 1000
    store.save_result(run, result)
    store.append(parent, 'assistant', 'done')
    child = SessionService(store).fork(parent, store.messages(parent)[-1]['id'], 'child')
    controller = AgentController(store)
    before = controller.state.read(child)
    with pytest.raises(ValueError):
        controller.prepare(child, '解释结果', model_id='m', selected_ids=[])
    assert controller.state.read(child) == before
    assert store.messages(child) == []


def test_changed_branch_does_not_prevent_user_cancellation(tmp_path):
    store, child, run = branched(tmp_path)
    controller = AgentController(store)
    pending = controller.prepare(child, '继续', model_id='m', selected_ids=[])
    store.save_result(run, {'kind': 'review', 'issues': []})
    controller.cancel(pending)
    assert controller.state.read(child)['cancelled']


def test_historical_file_cannot_be_promoted_to_current_target(tmp_path):
    store, child, _ = branched(tmp_path)
    controller = AgentController(store)
    pending = controller.prepare(child, '继续审核', model_id='m', selected_ids=[])
    payload = response(pending.request)
    payload.update(message_intent='execute', next_action='plan', goal='审核历史文件',
                   skill_ids=['report.review'], targets=['f'])
    with pytest.raises(ValueError, match='Unknown file'):
        controller.complete(pending, payload)
    assert store.runs(child) == []


def test_compound_branch_contains_review_and_generated_artifact_metadata(tmp_path, monkeypatch):
    from test_step_delivery import reviewed
    store, parent, run = reviewed(tmp_path, monkeypatch, with_issues=True)
    store.append(parent, 'assistant', 'done')
    child = SessionService(store).fork(parent, store.messages(parent)[-1]['id'], 'child')
    pending = AgentController(store).prepare(child, '解释生成后审核的结果', model_id='m', selected_ids=[])
    text = pending.request.context[0].text
    assert 'history_fragment.docx' in text and '合成测试意见' in text
    assert run in text and str(tmp_path) not in text
    assert not pending.request.files
