"""S01 现状冻结：分支。

正确行为（必须通过）：fork 只记录锚点与完成 Run 引用，不复制消息/授权。
已知缺陷（xfail）：SES-09 分支不是消息树，子会话上下文看不到锚点前的普通对话。
"""
import pytest
from test_consultation_routing import make_store


def test_fork_copies_no_messages_or_authorization(tmp_path):
    from asset_based_agent.technical_platform.session_service import SessionService
    store, _project, parent = make_store(tmp_path)
    store.append(parent, 'user', '父会话消息')
    store.append(parent, 'assistant', '父会话回复')
    anchor = store.messages(parent)[0]['id']
    child = SessionService(store).fork(parent, anchor, '分支')
    assert store.messages(child) == [], 'fork 不得复制普通消息'


@pytest.mark.xfail(reason='SES-09：分支只快照 Run 引用，普通父对话不进入子会话上下文', strict=True)
def test_branch_inherits_parent_plain_conversation_as_readonly_context(tmp_path):
    from asset_based_agent.technical_platform.branch_understanding import (
        branch_messages,
    )
    from asset_based_agent.technical_platform.session_service import SessionService
    store, _project, parent = make_store(tmp_path)
    store.append(parent, 'user', '父会话里的关键背景')
    anchor = store.messages(parent)[0]['id']
    child = SessionService(store).fork(parent, anchor, '分支')
    context = branch_messages(store, child)
    assert any('父会话里的关键背景' in item['text'] for item in context), \
        '分支应继承锚点前的只读对话语义'
