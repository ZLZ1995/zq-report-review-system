"""K06：咨询、澄清、取消、执行四类状态互不串扰。

待澄清任务存在时：独立咨询只回答并保留 pending；明确回答澄清才恢复原任务；
明确说取消才取消；发起新执行任务时明确替换旧任务，绝不静默拼接澄清上下文。
"""
from test_consultation_routing import SpyClient, make_store
from test_platform_queries import add_named_file, scripted_spy

from asset_based_agent.technical_platform.conversation_state import ConversationState


def load_router():
    from asset_based_agent.technical_platform.turn_router import TurnRouter
    return TurnRouter


def set_pending_question(store, session, text='要选择哪份文件作为审核对象？'):
    state = ConversationState(store)
    revision = state.start(session, expected_revision=state.read(session)['revision'])['revision']
    state.ask(session, revision, text)
    return state.read(session)


def plan_spy(file_id, *, intent='execute', reply='好的，按这份处理。'):
    """返回脚本化 plan 裁决的间谍客户端；禁止任何其他客户端方法。"""
    spy = SpyClient()
    def understand(payload, *, cancel=None):
        spy.understand_calls.append(payload)
        return {'schema_version': 1, 'message_intent': intent, 'goal': '审核报告',
                'targets': [file_id], 'references': [], 'excluded': [], 'constraints': [],
                'deliverables': ['审核意见'], 'missing_inputs': [],
                'evidence_message_ids': [payload['message_id']],
                'skill_ids': ['report.review'], 'next_action': 'plan', 'reply': reply}
    spy.understand_task = understand
    return spy


def test_clarify_answer_resumes_original_task(tmp_path):
    """用户明确回答澄清问题：恢复原任务，沿用原 task_id 与原信封约束。"""
    store, project, session = make_store(tmp_path)
    file_id = add_named_file(store, project, tmp_path, '审核报告.docx', '报告正文')
    before = set_pending_question(store, session)
    spy = plan_spy(file_id, intent='execute')
    outcome = load_router()(store, spy).submit(
        session, '用审核报告.docx这份', model_id='m', selected_ids=[file_id])
    assert outcome.kind == 'execution'
    pending = outcome.pending
    assert pending.task_id == before['task_id'], '回答澄清必须恢复原任务'
    assert pending.revision > before['revision']
    # 恢复的理解请求必须带原澄清问题上下文
    assert any('审核对象' in getattr(m, 'text', '') for m in pending.request.context)


def test_execute_during_pending_is_explicit_continuation(tmp_path):
    """待澄清期间的执行裁决：显式继续原任务并告知用户，绝不静默拼接。"""
    store, project, session = make_store(tmp_path)
    file_id = add_named_file(store, project, tmp_path, '明细表.xlsx', '科目表头')
    before = set_pending_question(store, session)
    spy = plan_spy(file_id, intent='execute')
    outcome = load_router()(store, spy).submit(
        session, '不管之前那个了，直接核对明细表.xlsx', model_id='m', selected_ids=[file_id])
    assert outcome.kind == 'execution'
    pending = outcome.pending
    assert pending.task_id == before['task_id'], '待澄清期间继续原任务，不另起静默任务'
    texts = [m['text'] for m in store.messages(session)]
    assert any('正在继续上一个等待补充信息的任务' in t and '取消' in t for t in texts), \
        '继续必须显式告知用户，并给出“取消”的另起任务出口'
    state = ConversationState(store).read(session)
    assert not state['cancelled']


def test_explicit_cancel_cancels_pending_task(tmp_path):
    """用户明确说取消：目标任务被取消，且不创建新任务。"""
    store, _project, session = make_store(tmp_path)
    before = set_pending_question(store, session)
    spy = SpyClient()
    def understand(payload, *, cancel=None):
        spy.understand_calls.append(payload)
        return {'schema_version': 1, 'message_intent': 'cancel', 'goal': '取消任务',
                'targets': [], 'references': [], 'excluded': [], 'constraints': [],
                'deliverables': [], 'missing_inputs': [],
                'evidence_message_ids': [payload['message_id']],
                'skill_ids': [], 'next_action': 'cancel', 'reply': '已取消当前任务。'}
    spy.understand_task = understand
    outcome = load_router()(store, spy).submit(
        session, '取消刚才的任务', model_id='m', selected_ids=[])
    assert outcome.kind == 'cancel'
    assert outcome.reply == '已取消当前任务。'
    state = ConversationState(store).read(session)
    assert state['cancelled'] and state['question'] is None
    assert state['task_id'] == before['task_id'], '取消针对原任务，不另起任务'


def test_consult_during_pending_keeps_question(tmp_path):
    """待澄清期间的独立咨询：回答问题，pending 原样保留（K01-8 的 K06 复核）。"""
    store, _project, session = make_store(tmp_path)
    before = set_pending_question(store, session)
    spy = scripted_spy('在首页选择项目后即可上传文件。')
    outcome = load_router()(store, spy).submit(
        session, '这个功能怎么用？', model_id='m', selected_ids=[])
    assert outcome.kind == 'answer'
    after = ConversationState(store).read(session)
    assert after['task_id'] == before['task_id']
    assert after['question'] and '审核对象' in after['question']['text']
    assert not after['cancelled']
