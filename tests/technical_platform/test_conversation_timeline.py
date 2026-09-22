"""S16：对话时间线投影（测试先行）。

契约（施工文件 2.1/4.3）：
- 顺序：用户消息 → 本轮 live 状态 → 助手回复 → 该轮成果 → 下一轮…；
- 成果紧跟产生它的 assistant 消息，不因新消息移动到末尾；
- 普通聊天不带出任何历史成果；
- 不可唯一归属的 legacy run 进入独立旧成果区域，不挂在最新回复下；
- live 状态插在对应用户消息之后，完成后消失。
"""
from asset_based_agent.technical_platform.conversation_timeline import (
    TimelineItem,
    project_timeline,
)
from types import SimpleNamespace


def msg(mid, role, text, created='2026-09-01T09:00:00+00:00'):
    return {'id': mid, 'role': role, 'text': text, 'created': created}


def run(rid, state='succeeded', created='2026-09-01T09:00:01+00:00'):
    return {'id': rid, 'state': state, 'snapshot': '{}',
            'result': '{"kind":"generation"}', 'created': created}


def link(rid, source, assistant, relation='exact'):
    return {'run_id': rid, 'source_message_id': source,
            'assistant_message_id': assistant, 'relation': relation,
            'created_at': '2026-09-01T09:00:02+00:00'}


def kinds(items):
    return [item.kind for item in items]


def test_empty_session_projects_nothing():
    assert project_timeline([], [], []) == []


def test_artifacts_follow_their_own_assistant_message():
    messages = [
        msg(1, 'user', '生成明细表'),
        msg(2, 'assistant', '已生成 3 个文件。'),
        msg(3, 'user', '你好'),
        msg(4, 'assistant', '你好，请问核对哪些资料？'),
    ]
    items = project_timeline(messages, [link('r1', 1, 2)], [run('r1')])
    assert kinds(items) == ['user', 'assistant', 'artifacts', 'user', 'assistant']
    artifacts = items[2]
    assert artifacts.run_id == 'r1'
    assert artifacts.message_id == 2  # 锚定第一轮回复
    # 第二轮普通聊天不带出历史成果
    assert items[4].kind == 'assistant' and items[4].message_id == 4


def test_legacy_unlinked_runs_go_to_separate_zone_not_latest_reply():
    messages = [msg(1, 'user', '你好'), msg(2, 'assistant', '你好。')]
    links = [link('rold', None, None, relation='legacy_unlinked')]
    items = project_timeline(messages, links, [run('rold')])
    assert kinds(items) == ['user', 'assistant', 'legacy_artifacts']
    zone = items[-1]
    assert zone.payload['runs'][0]['id'] == 'rold'


def test_live_status_sits_after_its_user_message_and_disappears():
    messages = [msg(1, 'user', '生成明细表')]
    live = {'after_message_id': 1, 'text': '正在生成…', 'operation_id': 'op1'}
    items = project_timeline(messages, [], [], live_status=live)
    assert kinds(items) == ['user', 'live_status']
    assert items[1].payload['text'] == '正在生成…'
    # 完成后 live 消失，回复与成果落位
    done = project_timeline(
        messages + [msg(2, 'assistant', '已生成。')],
        [link('r1', 1, 2)], [run('r1')])
    assert kinds(done) == ['user', 'assistant', 'artifacts']


def test_event_messages_and_inferred_links_render_in_place():
    messages = [
        msg(1, 'user', '审核这份报告'),
        msg(2, 'event', '任务已取消。'),
        msg(3, 'assistant', '审核完成。'),
    ]
    items = project_timeline(
        messages, [link('r9', 1, 3, relation='legacy_inferred')], [run('r9')])
    assert kinds(items) == ['user', 'event', 'assistant', 'artifacts']
    assert items[3].run_id == 'r9'


def test_runs_without_links_and_active_states_do_not_leak():
    messages = [msg(1, 'user', '你好'), msg(2, 'assistant', '你好。')]
    orphan = run('r-orphan')  # 无关联行（极端旧数据）
    active = run('r-active', state='running')
    items = project_timeline(messages, [], [orphan, active])
    assert kinds(items) == ['user', 'assistant', 'legacy_artifacts']
    zone_ids = [r['id'] for r in items[-1].payload['runs']]
    assert zone_ids == ['r-orphan']  # 进行中的 run 不进成果区


def test_timeline_item_is_stable_viewmodel():
    item = TimelineItem(kind='assistant', message_id=7)
    assert item.kind == 'assistant'
    assert item.message_id == 7
    assert item.run_id is None and item.payload == {}


def test_mixed_agent_and_legacy_entries_merge_chronologically_and_keep_artifact_anchor():
    timestamp = lambda second: f'2026-09-01T09:00:{second:02d}+00:00'
    messages = [
        msg(1, 'user', '你好', timestamp(1)),
        msg(2, 'assistant', '你好呀', timestamp(2)),
        msg(3, 'user', '你好', timestamp(3)),
        msg(4, 'assistant', '你好呀', timestamp(4)),
    ]
    entries = [
        SimpleNamespace(id=10, entry_type='user_message',
                        created_at=timestamp(1),
                        payload={'text': '你好', '_legacy_message_id': '1'}),
        SimpleNamespace(id=20, entry_type='assistant_message',
                        created_at=timestamp(2),
                        payload={'text': '你好呀', '_legacy_message_id': '2'}),
        SimpleNamespace(id=30, entry_type='user_message',
                        created_at=timestamp(3),
                        payload={'text': '你好', '_legacy_message_id': '3'}),
        SimpleNamespace(id=40, entry_type='assistant_message',
                        created_at=timestamp(4),
                        payload={'text': '你好呀', '_legacy_message_id': '4'}),
        SimpleNamespace(id=50, entry_type='user_message',
                        created_at=timestamp(5), payload={'text': '新问题'}),
        SimpleNamespace(id=60, entry_type='assistant_message',
                        created_at=timestamp(6), payload={'text': '新回答'}),
    ]

    items = project_timeline(
        messages, [link('r1', 1, 2)], [run('r1', created=timestamp(2))],
        agent_entries=entries)

    assert kinds(items) == [
        'user', 'assistant', 'artifacts', 'user', 'assistant', 'user', 'assistant']
    assert [item.payload.get('text') for item in items
            if item.kind in {'user', 'assistant'}] == [
                '你好', '你好呀', '你好', '你好呀', '新问题', '新回答']
    assert items[2].message_id == 20
    assert items[3].payload['_legacy_message_id'] == '3'


def test_mixed_projection_deduplicates_only_the_mirrored_legacy_message_id():
    messages = [msg(1, 'user', '重复文本'), msg(2, 'user', '重复文本',
                                             '2026-09-01T09:00:03+00:00')]
    entries = [SimpleNamespace(
        id=20, entry_type='user_message', created_at='2026-09-01T09:00:03+00:00',
        payload={'text': '重复文本', '_legacy_message_id': '2'})]

    items = project_timeline(messages, [], [], agent_entries=entries)

    assert [(item.kind, item.payload.get('text')) for item in items] == [
        ('user', '重复文本'), ('user', '重复文本')]
