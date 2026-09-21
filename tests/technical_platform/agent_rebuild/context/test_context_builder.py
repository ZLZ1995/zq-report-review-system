"""S10：ContextBuilder——固定装配顺序、预算、lane 隔离、秘密遮蔽与事实门禁。"""
import asyncio
from uuid import uuid4

from asset_based_agent.technical_platform.agent_core.context_builder import (
    ContextBuilder,
)
from asset_based_agent.technical_platform.agent_core.contracts import (
    ModelEvent,
    ToolDescriptor,
)
from asset_based_agent.technical_platform.agent_core.fakes import (
    FakeModelPort,
    InMemorySessionRepo,
)
from asset_based_agent.technical_platform.agent_core.runtime import AgentKernel


def run(coro):
    return asyncio.run(coro)


def make_repo():
    repo = InMemorySessionRepo()
    repo.create_session('s1', project_id='p1', owner_id='alice', title='会话',
                        permission_mode='assisted')
    return repo


def add_turn(repo, user, assistant, lane='main', session='s1'):
    operation = repo.begin_operation(session, lane, user_text=user,
                                     request_id=uuid4().hex)
    entry = repo.append_entry(session, lane, 'assistant_message',
                              {'text': assistant}, operation_id=operation.id)
    repo.complete_operation(operation.id, assistant_entry_id=entry.id,
                            turn_id=None)
    return operation


def current_operation(repo, text='当前问题', lane='main'):
    return repo.begin_operation('s1', lane, user_text=text,
                                request_id=uuid4().hex)


def tool(name='probe', risk='local_readonly'):
    class _Tool:
        descriptor = ToolDescriptor(name=name, description='d',
                                    input_schema={}, risk=risk)
    return _Tool()


def texts(built):
    return [m['payload'].get('text', '') for m in built.messages]


def test_sections_follow_spec_order():
    repo = make_repo()
    add_turn(repo, '第一轮问题', '第一轮回答')
    operation = current_operation(repo)
    repo.set_resource_snapshot(operation.id, [
        {'skill_id': 'skill-a', 'version': '1.0.0', 'sha256': 'a' * 64}])
    fact_id = repo.propose_fact('p1', 'project', '口径', '保守')
    repo.set_fact_status(fact_id, 'confirmed')
    repo.bind_file(operation.id, 'file-b', 'explicit_upload', sha256='b' * 64)
    built = ContextBuilder().build(repo=repo, operation=operation,
                                   tools=[tool()])
    joined = texts(built)
    order = ['【系统安全规则】', '【Agent 行为规则】', '【当前权限快照】',
             '【当前 Tool 描述】', '【Skill 固定规则】', '【项目 confirmed overlay】',
             '第一轮问题', '【本轮文件摘要】', '当前问题']
    positions = []
    for marker in order:
        index = next((i for i, text in enumerate(joined) if marker in text), -1)
        assert index >= 0, marker
        positions.append(index)
    assert positions == sorted(positions)
    assert built.messages[-1]['payload']['text'] == '当前问题'
    permission = next(t for t in joined if '【当前权限快照】' in t)
    assert 'assisted' in permission
    skill = next(t for t in joined if '【Skill 固定规则】' in t)
    assert 'skill-a@1.0.0' in skill
    assert 'file-b' in next(t for t in joined if '【本轮文件摘要】' in t)


def test_token_budget_drops_oldest_turns_but_keeps_rules_and_current():
    repo = make_repo()
    for index in range(30):
        add_turn(repo, f'第{index}轮' + '长' * 200, '回答' + '长' * 200)
    operation = current_operation(repo, '预算内的当前问题')
    built = ContextBuilder(token_budget=2000).build(
        repo=repo, operation=operation, tools=[tool()])
    joined = '\n'.join(texts(built))
    assert '【系统安全规则】' in joined
    assert '预算内的当前问题' in joined
    assert built.report['dropped_entries'] > 0
    assert built.report['tokens'] <= built.report['budget']
    assert '第0轮' not in joined  # 最旧的轮次最先被丢弃


def test_other_lane_content_never_leaks():
    repo = make_repo()
    add_turn(repo, '主线内容', '主线回答')
    anchor = repo.entries('s1', 'main')[0]
    repo.create_lane('s1', 'branch', name='分支', parent_lane_id='main',
                     anchor_entry_id=anchor.id)
    add_turn(repo, '分支私密标记XYZ', '分支回答', lane='branch')
    operation = current_operation(repo)
    built = ContextBuilder().build(repo=repo, operation=operation, tools=[])
    assert '分支私密标记XYZ' not in '\n'.join(texts(built))


def test_branch_lane_inherits_parent_chain():
    repo = make_repo()
    add_turn(repo, '父链标记问题', '父链标记回答')
    anchor = repo.entries('s1', 'main')[-1]
    repo.create_lane('s1', 'branch', name='分支', parent_lane_id='main',
                     anchor_entry_id=anchor.id)
    operation = current_operation(repo, '分支当前问题', lane='branch')
    built = ContextBuilder().build(repo=repo, operation=operation, tools=[])
    joined = '\n'.join(texts(built))
    assert '父链标记问题' in joined and '分支当前问题' in joined


def test_secrets_are_redacted_from_history():
    repo = make_repo()
    add_turn(repo, '我的 password=abc123456 帮我看看', '好的，token=zzz999 已收到')
    operation = current_operation(repo)
    built = ContextBuilder().build(repo=repo, operation=operation, tools=[])
    joined = '\n'.join(texts(built))
    assert 'abc123456' not in joined and 'zzz999' not in joined
    assert '[已遮蔽]' in joined


def test_only_confirmed_facts_enter_context():
    repo = make_repo()
    confirmed = repo.propose_fact('p1', 'project', '口径', '保守')
    repo.set_fact_status(confirmed, 'confirmed')
    repo.propose_fact('p1', 'project', '推测', '也许是A')  # 未确认推测
    rejected = repo.propose_fact('p1', 'project', '旧值', 'X')
    repo.set_fact_status(rejected, 'rejected')
    operation = current_operation(repo)
    built = ContextBuilder().build(repo=repo, operation=operation, tools=[])
    joined = '\n'.join(texts(built))
    assert '口径' in joined and '保守' in joined
    assert '也许是A' not in joined and '旧值' not in joined


def test_file_summary_uses_current_operation_bindings_only():
    repo = make_repo()
    past = add_turn(repo, '上传了旧文件', '收到旧文件')
    repo.bind_file(past.id, 'file-old', 'explicit_upload', sha256='o' * 64)
    operation = current_operation(repo)
    repo.bind_file(operation.id, 'file-new', 'explicit_upload', sha256='n' * 64)
    built = ContextBuilder().build(repo=repo, operation=operation, tools=[])
    summary = next(t for t in texts(built) if '【本轮文件摘要】' in t)
    assert 'file-new' in summary and 'file-old' not in summary


def test_historical_file_catalog_includes_stable_ids_for_follow_up_reads():
    repo = make_repo()
    repo.legacy_project_files = lambda _project_id: [
        {'id': 'history-1', 'name': 'old.xlsx'},
    ]
    operation = current_operation(repo, 'read the historical workbook')
    built = ContextBuilder().build(repo=repo, operation=operation, tools=[])
    joined = '\n'.join(texts(built))
    assert 'old.xlsx' in joined
    assert 'history-1' in joined


def test_kernel_uses_context_builder_when_provided():
    repo = make_repo()
    scripts = [[ModelEvent('message_start', {}),
                ModelEvent('text_delta', {'text': '好'}),
                ModelEvent('message_complete', {})]]
    model = FakeModelPort(scripts)
    kernel = AgentKernel(repo=repo, model=model,
                         context_builder=ContextBuilder())
    run(kernel.submit('s1', 'main', {'text': '你好'}))
    messages = model.requests[0].messages
    assert '【系统安全规则】' in messages[0]['payload']['text']
    assert messages[-1]['payload']['text'] == '你好'


def test_kernel_without_context_builder_keeps_legacy_request():
    repo = make_repo()
    scripts = [[ModelEvent('message_start', {}),
                ModelEvent('text_delta', {'text': '好'}),
                ModelEvent('message_complete', {})]]
    model = FakeModelPort(scripts)
    kernel = AgentKernel(repo=repo, model=model)
    run(kernel.submit('s1', 'main', {'text': '你好'}))
    roles = [m['role'] for m in model.requests[0].messages]
    assert roles == ['user_message']  # 无 system 段，保持 S05 行为
