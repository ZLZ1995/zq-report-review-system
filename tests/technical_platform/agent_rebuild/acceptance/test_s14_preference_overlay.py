# S14 10.3 个性化层级：项目 confirmed overlay > 用户 preference overlay > 本轮指令。
from uuid import uuid4

from asset_based_agent.technical_platform.agent_core.context_builder import (
    ContextBuilder,
)
from asset_based_agent.technical_platform.agent_core.fakes import (
    InMemorySessionRepo,
)


def make_repo():
    repo = InMemorySessionRepo()
    repo.create_session('s1', project_id='p1', owner_id='alice', title='会话',
                        permission_mode='assisted')
    return repo


def test_overlay_layers_follow_spec_order():
    repo = make_repo()
    project_fact = repo.propose_fact('p1', 'project', '口径', '集团合并')
    user_fact = repo.propose_fact('p1', 'user', '偏好', '表格保留两位小数')
    repo.set_fact_status(project_fact, 'confirmed')
    repo.set_fact_status(user_fact, 'confirmed')
    operation = repo.begin_operation('s1', 'main', user_text='本轮指令',
                                     request_id=uuid4().hex)
    built = ContextBuilder().build(repo=repo, operation=operation)
    texts = [m['payload'].get('text', '') for m in built.messages]
    project_layer = next(i for i, t in enumerate(texts)
                         if '项目 confirmed overlay' in t)
    user_layer = next(i for i, t in enumerate(texts)
                      if '用户 preference overlay' in t)
    file_layer = next(i for i, t in enumerate(texts) if '本轮文件摘要' in t)
    assert '集团合并' in texts[project_layer]
    assert '两位小数' in texts[user_layer]
    # 安全规则 > Skill 规则 > 项目 overlay > 用户 overlay > 文件摘要/本轮指令
    assert project_layer < user_layer < file_layer
    assert texts[0].startswith('【') and '安全' in texts[0]
    assert built.messages[-1]['role'] == 'user_message'


def test_unscoped_facts_stay_in_project_overlay():
    repo = make_repo()
    fact = repo.propose_fact('p1', 'project', '主体', '母公司')
    repo.set_fact_status(fact, 'confirmed')
    operation = repo.begin_operation('s1', 'main', user_text='问',
                                     request_id=uuid4().hex)
    built = ContextBuilder().build(repo=repo, operation=operation)
    texts = [m['payload'].get('text', '') for m in built.messages]
    assert any('项目 confirmed overlay' in t and '母公司' in t
               for t in texts)
    assert not any('用户 preference overlay' in t for t in texts)


def test_proposed_facts_never_enter_overlay():
    repo = make_repo()
    repo.propose_fact('p1', 'user', '未确认', '猜测值')
    operation = repo.begin_operation('s1', 'main', user_text='问',
                                     request_id=uuid4().hex)
    built = ContextBuilder().build(repo=repo, operation=operation)
    texts = [m['payload'].get('text', '') for m in built.messages]
    assert not any('猜测值' in t for t in texts)
