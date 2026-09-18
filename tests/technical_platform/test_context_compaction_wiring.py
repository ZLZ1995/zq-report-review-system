"""澄清上下文压缩接入主路径（conversation_compactor × agent_controller）。

验收：多轮澄清超界时先压缩（摘要带非原始证据标记与回查线索）而不是直接
拒绝；PREFIX 分支参考永不入摘要；压缩后仍超界才 ClarificationContextLimit；
短对话行为与接线前完全一致；存储的原始消息不受压缩影响。
"""
import pytest

from asset_based_agent.technical_platform.store import PlatformStore


def response(request, *, ask=True, reply='要审核还是生成？'):
    return {'schema_version': 1, 'message_intent': 'clarify' if ask else 'consult',
            'goal': '', 'targets': [], 'references': [], 'excluded': [],
            'constraints': [], 'deliverables': [],
            'missing_inputs': [{'field': 'goal', 'question': reply}] if ask else [],
            'evidence_message_ids': [request.message_id], 'skill_ids': [],
            'next_action': 'ask' if ask else 'answer', 'reply': reply}


def drive_rounds(controller, session, rounds, *, filler=2000):
    """连续多轮澄清，每轮用户输入带填充文本。返回最后一次 pending。"""
    pending = None
    for index in range(rounds):
        pending = controller.prepare(
            session, f'第{index}轮补充要求' + '要' * filler,
            model_id='m', selected_ids=[])
        controller.complete(pending, response(pending.request))
    return pending


def test_long_clarification_compacts_instead_of_rejecting(tmp_path):
    from asset_based_agent.technical_platform.agent_controller import AgentController
    store = PlatformStore(tmp_path / 'db.sqlite', 'alice')
    session = store.create_session(store.create_project('one'))
    controller = AgentController(store)
    pending = drive_rounds(controller, session, 8, filler=2000)
    ids = [m.id for m in pending.request.context]
    assert any(item.startswith('sum-') for item in ids), ids
    summary = next(m for m in pending.request.context if m.id.startswith('sum-'))
    assert '非原始证据' in summary.text


def test_compaction_keeps_recent_tail_verbatim(tmp_path):
    from asset_based_agent.technical_platform.agent_controller import AgentController
    store = PlatformStore(tmp_path / 'db.sqlite', 'alice')
    session = store.create_session(store.create_project('one'))
    controller = AgentController(store)
    pending = drive_rounds(controller, session, 8, filler=2000)
    texts = [m.text for m in pending.request.context]
    assert any('第6轮补充要求' in text for text in texts)


def test_stored_messages_untouched_by_compaction(tmp_path):
    from asset_based_agent.technical_platform.agent_controller import AgentController
    store = PlatformStore(tmp_path / 'db.sqlite', 'alice')
    session = store.create_session(store.create_project('one'))
    controller = AgentController(store)
    drive_rounds(controller, session, 8, filler=2000)
    stored = store.messages(session)
    assert len(stored) == 16  # 8 轮 ×（用户+助手），原文一条不少
    assert any('第0轮补充要求' in m['text'] for m in stored)


def test_short_clarification_behavior_unchanged(tmp_path):
    from asset_based_agent.technical_platform.agent_controller import AgentController
    store = PlatformStore(tmp_path / 'db.sqlite', 'alice')
    session = store.create_session(store.create_project('one'))
    controller = AgentController(store)
    pending = drive_rounds(controller, session, 2, filler=10)
    assert not any(m.id.startswith('sum-') for m in pending.request.context)


def test_uncompactable_overflow_still_fails_explicitly(tmp_path, monkeypatch):
    """压缩无法降压（如分支参考本身超大）时，必须明确拒绝而非静默丢弃。"""
    from asset_based_agent.technical_platform.agent_controller import (
        AgentController,
        ClarificationContextLimit,
    )
    monkeypatch.setattr(
        'asset_based_agent.technical_platform.context_assembly'
        '.compact_clarification_context',
        lambda context, **_: list(context))  # 模拟压缩无能为力的场景
    store = PlatformStore(tmp_path / 'db.sqlite', 'alice')
    session = store.create_session(store.create_project('one'))
    controller = AgentController(store)
    with pytest.raises(ClarificationContextLimit):
        drive_rounds(controller, session, 6, filler=10)


def test_compact_helper_preserves_branch_reference():
    from asset_based_agent.technical_platform.branch_understanding import PREFIX
    from asset_based_agent.technical_platform.context_assembly import (
        compact_clarification_context,
    )
    context = [{'id': PREFIX + 'abc', 'role': 'assistant', 'text': '分支参考'}]
    context += [{'id': f'm{i}', 'role': 'user' if i % 2 else 'assistant',
                 'text': f'第{i}条' + 'x' * 100} for i in range(12)]
    result = compact_clarification_context(context, keep_recent=4)
    assert result[0]['id'] == PREFIX + 'abc'
    assert result[0]['text'] == '分支参考'
    summary = next(m for m in result if m['id'].startswith('sum-'))
    assert PREFIX + 'abc' not in summary['id']
    assert len(result) == 1 + 1 + 4  # 分支参考 + 摘要 + 4 条近轮


def test_compact_helper_summary_carries_source_ids():
    from asset_based_agent.technical_platform.context_assembly import (
        compact_clarification_context,
    )
    context = [{'id': f'm{i}', 'role': 'user', 'text': f'内容{i}'}
               for i in range(9)]
    result = compact_clarification_context(context, keep_recent=4)
    summary = result[0]
    assert summary['id'].startswith('sum-')
    assert '非原始证据' in summary['text']
    assert 'm0' in summary['text']  # 回查线索：被折叠消息 id 内联保留


def test_resume_after_compaction_passes_identity_check(tmp_path):
    from asset_based_agent.technical_platform.agent_controller import AgentController
    store = PlatformStore(tmp_path / 'db.sqlite', 'alice')
    session = store.create_session(store.create_project('one'))
    controller = AgentController(store)
    drive_rounds(controller, session, 8, filler=2000)
    reopened = AgentController(store)  # 模拟重启后继续澄清
    pending = reopened.prepare(session, '继续补充', model_id='m', selected_ids=[])
    assert any(m.id.startswith('sum-') for m in pending.request.context)
    result = reopened.complete(pending, response(pending.request, ask=False,
                                                 reply='明白，只读审核。'))
    assert result.next_action == 'answer'
