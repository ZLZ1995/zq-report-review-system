"""G09：统一事件、对话流式交付和任务面板。

验收：所有长阶段持续有真实事件或明确等待原因；停止按钮可用（cancellable）；
重启恢复后不复制消息或成果；百分比只作辅助，不能长期停在无法解释的状态。
"""


def ts(n):
    return f'2026-09-18T10:00:{n:02d}Z'


def make_journal(tmp_path, events=None):
    from asset_based_agent.technical_platform.workflow_journal import WorkflowJournal
    journal = WorkflowJournal(tmp_path / 'journal.jsonl')
    for event in events or []:
        journal.append(**event)
    return journal


def standard_events():
    """两节点成功运行的完整事件序列。"""
    return [
        {'run_id': 'r1', 'node_id': None, 'type': 'run_created', 'at': ts(1)},
        {'run_id': 'r1', 'node_id': None, 'type': 'phase_started', 'at': ts(2),
         'payload': {'phase': '执行'}},
        {'run_id': 'r1', 'node_id': 's1', 'type': 'node_queued', 'at': ts(3)},
        {'run_id': 'r1', 'node_id': 's2', 'type': 'node_queued', 'at': ts(4)},
        {'run_id': 'r1', 'node_id': 's1', 'type': 'node_started', 'at': ts(5)},
        {'run_id': 'r1', 'node_id': 's1', 'type': 'node_progress', 'at': ts(6),
         'payload': {'channel': 'model', 'message': '正在生成第 3 段'}},
        {'run_id': 'r1', 'node_id': 's1', 'type': 'node_succeeded', 'at': ts(7)},
        {'run_id': 'r1', 'node_id': 's1', 'type': 'node_result_committed',
         'at': ts(8)},
        {'run_id': 'r1', 'node_id': 's2', 'type': 'node_started', 'at': ts(9)},
        {'run_id': 'r1', 'node_id': 's2', 'type': 'node_succeeded', 'at': ts(10)},
        {'run_id': 'r1', 'node_id': 's2', 'type': 'node_result_committed',
         'at': ts(11)},
        {'run_id': 'r1', 'node_id': None, 'type': 'artifact_ready', 'at': ts(12),
         'payload': {'name': '审核报告.docx', 'artifact_id': 'a1'}},
        {'run_id': 'r1', 'node_id': None, 'type': 'phase_completed', 'at': ts(13),
         'payload': {'phase': '执行'}},
        {'run_id': 'r1', 'node_id': None, 'type': 'run_terminal', 'at': ts(14),
         'payload': {'state': 'succeeded'}},
    ]


# ---- 任务面板投影 ----

def test_empty_panel_defaults(tmp_path):
    from asset_based_agent.technical_platform.task_panel import project_panel
    state = project_panel(make_journal(tmp_path), 'r1')
    assert state.run_id == 'r1'
    assert state.phase is None
    assert state.current_node is None
    assert state.completed_nodes == 0
    assert state.total_nodes == 0
    assert state.wait_reason is None
    assert state.cancellable is True
    assert state.terminal is None


def test_panel_counts_and_current_node(tmp_path):
    from asset_based_agent.technical_platform.task_panel import project_panel
    events = standard_events()[:9]  # s1 已成功，s2 已开始
    state = project_panel(make_journal(tmp_path, events), 'r1')
    assert state.total_nodes == 2
    assert state.completed_nodes == 1
    assert state.current_node == 's2'
    assert state.phase == '执行'
    assert state.last_activity_at == ts(9)
    assert state.cancellable is True


def test_panel_terminal_state_disables_cancel(tmp_path):
    from asset_based_agent.technical_platform.task_panel import project_panel
    state = project_panel(make_journal(tmp_path, standard_events()), 'r1')
    assert state.terminal == 'succeeded'
    assert state.cancellable is False
    assert state.completed_nodes == 2
    assert state.current_node is None
    assert state.phase is None


def test_panel_cancelled_terminal(tmp_path):
    from asset_based_agent.technical_platform.task_panel import project_panel
    events = standard_events()[:5] + [
        {'run_id': 'r1', 'node_id': None, 'type': 'run_terminal', 'at': ts(6),
         'payload': {'state': 'cancelled'}}]
    state = project_panel(make_journal(tmp_path, events), 'r1')
    assert state.terminal == 'cancelled'
    assert state.cancellable is False


def test_panel_waiting_resource_reason(tmp_path):
    from asset_based_agent.technical_platform.task_panel import project_panel
    events = standard_events()[:5] + [
        {'run_id': 'r1', 'node_id': 's1', 'type': 'node_waiting_resource',
         'at': ts(6), 'payload': {'reason': 'workbook:f1 被其他任务占用'}}]
    state = project_panel(make_journal(tmp_path, events), 'r1')
    assert state.wait_reason == 'workbook:f1 被其他任务占用'
    assert state.current_node == 's1'


def test_panel_waiting_user_reason(tmp_path):
    from asset_based_agent.technical_platform.task_panel import project_panel
    events = standard_events()[:5] + [
        {'run_id': 'r1', 'node_id': 's1', 'type': 'node_waiting_user',
         'at': ts(6), 'payload': {'reason': '等待确认覆盖副本'}}]
    state = project_panel(make_journal(tmp_path, events), 'r1')
    assert state.wait_reason == '等待确认覆盖副本'


def test_panel_retrying_keeps_node_current(tmp_path):
    from asset_based_agent.technical_platform.task_panel import project_panel
    events = standard_events()[:5] + [
        {'run_id': 'r1', 'node_id': 's1', 'type': 'node_retrying', 'at': ts(6),
         'payload': {'attempt': '2', 'error': 'TimeoutError'}}]
    state = project_panel(make_journal(tmp_path, events), 'r1')
    assert state.current_node == 's1'
    assert state.last_activity_at == ts(6)
    assert state.cancellable is True


def test_panel_ignores_other_runs(tmp_path):
    from asset_based_agent.technical_platform.task_panel import project_panel
    events = standard_events() + [
        {'run_id': 'r2', 'node_id': 'x1', 'type': 'node_queued', 'at': ts(15)}]
    state = project_panel(make_journal(tmp_path, events), 'r1')
    assert state.total_nodes == 2
    assert state.terminal == 'succeeded'


def test_progress_text_always_explains(tmp_path):
    from asset_based_agent.technical_platform.task_panel import (
        progress_text,
        project_panel,
    )
    events = standard_events()[:5] + [
        {'run_id': 'r1', 'node_id': 's1', 'type': 'node_waiting_resource',
         'at': ts(6), 'payload': {'reason': 'workbook:f1 被其他任务占用'}}]
    state = project_panel(make_journal(tmp_path, events), 'r1')
    text = progress_text(state)
    assert '0/2' in text
    assert 'workbook:f1 被其他任务占用' in text
    assert 's1' in text


def test_progress_text_no_bare_percent_stall(tmp_path):
    from asset_based_agent.technical_platform.task_panel import (
        progress_text,
        project_panel,
    )
    state = project_panel(make_journal(tmp_path, standard_events()[:6]), 'r1')
    text = progress_text(state)
    assert '0/2' in text  # 百分比之外必有计数与当前节点
    assert 's1' in text
    assert text.strip() != '0%'


# ---- 对话流式交付 ----

def test_stream_maps_all_channels(tmp_path):
    from asset_based_agent.technical_platform.conversation_stream import (
        ConversationStream,
    )
    journal = make_journal(tmp_path, [
        {'run_id': 'r1', 'node_id': 's1', 'type': 'node_progress', 'at': ts(1),
         'payload': {'channel': 'model', 'message': '生成中'}},
        {'run_id': 'r1', 'node_id': 's1', 'type': 'node_progress', 'at': ts(2),
         'payload': {'channel': 'parse', 'message': '解析第 2 页'}},
        {'run_id': 'r1', 'node_id': 's1', 'type': 'node_progress', 'at': ts(3),
         'payload': {'channel': 'office', 'message': '写入副本'}},
        {'run_id': 'r1', 'node_id': 's1', 'type': 'node_progress', 'at': ts(4),
         'payload': {'channel': 'browser', 'message': '打开 OA 页面'}},
        {'run_id': 'r1', 'node_id': 's1', 'type': 'node_progress', 'at': ts(5),
         'payload': {'channel': 'verify', 'message': '校验哈希'}},
        {'run_id': 'r1', 'node_id': 's1', 'type': 'node_progress', 'at': ts(6),
         'payload': {'channel': 'upload', 'message': '上传 40%'}},
        {'run_id': 'r1', 'node_id': 's1', 'type': 'node_progress', 'at': ts(7),
         'payload': {'channel': 'deliver', 'message': '交付成果'}},
    ])
    stream = ConversationStream.from_journal(journal, 'r1')
    kinds = [item.kind for item in stream.items()]
    assert kinds == ['model_delta', 'parse_status', 'office_progress',
                     'browser_action', 'verification', 'upload', 'delivery']
    assert stream.items()[0].text == '生成中'
    assert all(item.node_id == 's1' for item in stream.items())


def test_stream_phase_and_terminal_items(tmp_path):
    from asset_based_agent.technical_platform.conversation_stream import (
        ConversationStream,
    )
    stream = ConversationStream.from_journal(
        make_journal(tmp_path, standard_events()), 'r1')
    kinds = [item.kind for item in stream.items()]
    assert 'phase' in kinds
    assert kinds[-1] == 'terminal'
    assert any(item.kind == 'artifact' and '审核报告.docx' in item.text
               for item in stream.items())


def test_stream_waiting_items_carry_reason(tmp_path):
    from asset_based_agent.technical_platform.conversation_stream import (
        ConversationStream,
    )
    journal = make_journal(tmp_path, [
        {'run_id': 'r1', 'node_id': 's1', 'type': 'node_waiting_resource',
         'at': ts(1), 'payload': {'reason': '等待工作簿锁'}},
        {'run_id': 'r1', 'node_id': 's1', 'type': 'node_waiting_user',
         'at': ts(2), 'payload': {'reason': '等待用户确认'}},
    ])
    stream = ConversationStream.from_journal(journal, 'r1')
    texts = [item.text for item in stream.items()]
    assert any('等待工作簿锁' in text for text in texts)
    assert any('等待用户确认' in text for text in texts)


def test_stream_restore_is_idempotent(tmp_path):
    from asset_based_agent.technical_platform.conversation_stream import (
        ConversationStream,
    )
    path = tmp_path / 'journal.jsonl'
    journal = make_journal(tmp_path, standard_events())
    assert journal.path == path
    stream_a = ConversationStream.from_journal(journal, 'r1')
    stream_b = ConversationStream.from_journal(journal, 'r1')
    assert [i.model_dump() for i in stream_a.items()] == \
           [i.model_dump() for i in stream_b.items()]
    seqs = [item.seq for item in stream_a.items()]
    assert len(seqs) == len(set(seqs))


def test_stream_restore_after_restart_no_duplicates(tmp_path):
    from asset_based_agent.technical_platform.conversation_stream import (
        ConversationStream,
    )
    from asset_based_agent.technical_platform.workflow_journal import WorkflowJournal
    make_journal(tmp_path, standard_events())
    reloaded = WorkflowJournal(tmp_path / 'journal.jsonl')
    stream = ConversationStream.from_journal(reloaded, 'r1')
    names = [item.text for item in stream.items() if item.kind == 'artifact']
    assert len(names) == 1


def test_stream_items_ordered_by_event_seq(tmp_path):
    from asset_based_agent.technical_platform.conversation_stream import (
        ConversationStream,
    )
    stream = ConversationStream.from_journal(
        make_journal(tmp_path, standard_events()), 'r1')
    ats = [item.at for item in stream.items()]
    assert ats == sorted(ats)


def test_stream_ignores_other_runs(tmp_path):
    from asset_based_agent.technical_platform.conversation_stream import (
        ConversationStream,
    )
    journal = make_journal(tmp_path, standard_events() + [
        {'run_id': 'r2', 'node_id': 'x1', 'type': 'node_started', 'at': ts(15)}])
    stream = ConversationStream.from_journal(journal, 'r1')
    assert all(item.kind != 'node_status' or 'x1' not in (item.node_id or '')
               for item in stream.items())


def test_panel_and_stream_agree_on_terminal(tmp_path):
    from asset_based_agent.technical_platform.conversation_stream import (
        ConversationStream,
    )
    from asset_based_agent.technical_platform.task_panel import project_panel
    journal = make_journal(tmp_path, standard_events())
    state = project_panel(journal, 'r1')
    stream = ConversationStream.from_journal(journal, 'r1')
    assert state.terminal == 'succeeded'
    assert stream.items()[-1].kind == 'terminal'
    assert state.cancellable is False
