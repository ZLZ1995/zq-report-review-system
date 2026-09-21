"""S01 现状冻结：普通聊天。

正确行为（必须通过）：社交快路径与 stage-1 咨询回答不创建 run、消息成对落库。
已知缺陷（xfail）：SES-05 普通聊天历史不进入下一轮模型上下文，指代追问失效。
"""
import pytest
from test_consultation_routing import SpyClient, consult_response, make_store


def load_router():
    from asset_based_agent.technical_platform.turn_router import TurnRouter
    return TurnRouter


def test_social_greeting_fast_path_no_run_no_network(tmp_path):
    store, _project, session = make_store(tmp_path)
    spy = SpyClient()
    outcome = load_router()(store, spy).submit(session, '你好', model_id='m', selected_ids=[])
    assert outcome.kind == 'answer' and outcome.reply.strip()
    assert spy.understand_calls == [], '社交快路径不得发起远程理解'
    assert store.runs(session) == []
    assert [m['role'] for m in store.messages(session)] == ['user', 'assistant']


def test_capability_question_answered_by_consult_path(tmp_path):
    store, _project, session = make_store(tmp_path)
    spy = SpyClient()
    spy.understand_task = lambda payload, *, cancel=None: (
        spy.understand_calls.append(payload)
        or consult_response(payload, '我可以审核报告、生成评估明细表。'))
    outcome = load_router()(store, spy).submit(session, '你能帮我做什么', model_id='m', selected_ids=[])
    assert outcome.kind == 'answer'
    assert outcome.reply == '我可以审核报告、生成评估明细表。'
    assert len(spy.understand_calls) == 1
    assert store.runs(session) == []


@pytest.mark.xfail(reason='SES-05：普通聊天历史不进入模型上下文，指代追问没有上文', strict=True)
def test_pronoun_followup_sees_previous_plain_chat(tmp_path):
    store, _project, session = make_store(tmp_path)
    spy = SpyClient()
    spy.understand_task = lambda payload, *, cancel=None: (
        spy.understand_calls.append(payload) or consult_response(payload))
    router = load_router()(store, spy)
    router.submit(session, '资产负债表和利润表有什么区别？', model_id='m', selected_ids=[])
    router.submit(session, '那现金流量表呢？', model_id='m', selected_ids=[])
    assert len(spy.understand_calls) == 2
    context_text = str(spy.understand_calls[1]['context'])
    assert '资产负债表和利润表有什么区别' in context_text, '第二轮上下文未携带第一轮普通对话'
