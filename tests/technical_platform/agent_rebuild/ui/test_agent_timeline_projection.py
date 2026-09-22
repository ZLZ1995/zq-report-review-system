from types import SimpleNamespace

from asset_based_agent.technical_platform.conversation_timeline import (
    project_agent_timeline,
)


def entry(entry_id, entry_type, text, *, operation_id='op-1', intermediate=False):
    return SimpleNamespace(
        id=entry_id,
        entry_type=entry_type,
        payload={'text': text, 'intermediate': intermediate},
        operation_id=operation_id,
        created_at='2026-09-21T00:00:00+00:00',
    )


def test_agent_projection_renders_each_turn_once_and_hides_internal_entries():
    items = project_agent_timeline([
        entry('u1', 'user_message', '你好'),
        entry('a1', 'assistant_message', '先读取资料', intermediate=True),
        entry('t1', 'tool_call', 'internal'),
        entry('r1', 'tool_result', 'internal'),
        entry('a2', 'assistant_message', '最终回复'),
    ])

    assert [(item.kind, item.message_id, item.payload['text']) for item in items] == [
        ('user', 'u1', '你好'),
        ('assistant', 'a2', '最终回复'),
    ]


def test_agent_projection_keeps_failure_as_visible_event():
    items = project_agent_timeline([
        entry('u1', 'user_message', '执行任务'),
        entry('e1', 'error_message', '模型协议错误'),
    ])

    assert [item.kind for item in items] == ['user', 'event']
    assert items[-1].payload['text'] == '模型协议错误'


def test_agent_projection_shows_pending_user_before_live_reply():
    items = project_agent_timeline([], live_status={
        'operation_id': 'op-2', 'user_text': '正在执行', 'text': '处理中…',
    })

    assert [item.kind for item in items] == ['live_user', 'live_status']
