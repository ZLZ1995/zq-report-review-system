"""S07：Kernel 资源快照——accept 落快照、运行中更新隔离、
恢复必须使用原版本（找不到则失败，不得换版本重跑）。"""
import asyncio
import shutil

import pytest
from skill_fixtures import (
    echo_executor,
    make_registry,
    make_tool_registry,
    probe_tool,
    write_skill,
)

from asset_based_agent.technical_platform.agent_core.contracts import (
    ModelEvent,
)
from asset_based_agent.technical_platform.agent_core.errors import (
    ResourceVersionChanged,
)
from asset_based_agent.technical_platform.agent_core.fakes import (
    FakeModelPort,
    InMemorySessionRepo,
)
from asset_based_agent.technical_platform.agent_core.runtime import (
    AgentKernel,
)


def run(coro):
    return asyncio.run(coro)


def text_script(text='完成'):
    return [[ModelEvent('message_start', {}),
             ModelEvent('text_delta', {'text': text}),
             ModelEvent('message_complete', {})]]


def tool_then_text_scripts():
    return [
        [ModelEvent('message_start', {}),
         ModelEvent('tool_call_complete',
                    {'id': 'c1', 'name': 'probe', 'arguments': {}}),
         ModelEvent('message_complete', {})],
        [ModelEvent('message_start', {}),
         ModelEvent('text_delta', {'text': '完成'}),
         ModelEvent('message_complete', {})],
    ]


def setup_kernel(tmp_path, scripts, *, reply='v1回复', stream_factory=None):
    user = tmp_path / 'u'
    write_skill(user, 'probe-skill', '1.0.0',
                capabilities=['local_readonly'], tools=[probe_tool()],
                config={'reply': reply})
    registry = make_registry(tmp_path, user=user)
    tool_registry = make_tool_registry(
        registry, executors={'echo': echo_executor})
    repo = InMemorySessionRepo()
    repo.create_session('s1', project_id='p1', owner_id='alice', title='会话')
    if stream_factory is not None:
        model = FakeModelPort.from_stream_factory(stream_factory)
    else:
        model = FakeModelPort(list(scripts))
    kernel = AgentKernel(repo=repo, model=model, tool_resolver=tool_registry)
    return kernel, repo, registry, user, model


def test_submit_persists_resource_snapshot(tmp_path):
    kernel, repo, registry, _user, _model = setup_kernel(
        tmp_path, text_script())
    accepted = run(kernel.submit('s1', 'main', {'text': '你好'}))
    snapshot = repo.resource_snapshot(accepted.operation_id)
    discovered = registry.resolve('probe-skill')
    assert snapshot == [{
        'id': 'probe-skill', 'version': '1.0.0',
        'sha256': discovered.content_sha256, 'source': 'user'}], \
        'Operation accept 必须保存资源版本与 sha256'


def test_skill_update_during_run_does_not_affect_operation(tmp_path):
    gate = asyncio.Event()
    calls = []

    def factory(request, cancel):
        calls.append(1)
        if len(calls) == 1:
            async def gated():
                await gate.wait()
                yield ModelEvent('message_start', {})
                yield ModelEvent('tool_call_complete',
                                 {'id': 'c1', 'name': 'probe', 'arguments': {}})
                yield ModelEvent('message_complete', {})
            return gated()
        return [ModelEvent('message_start', {}),
                ModelEvent('text_delta', {'text': '完成'}),
                ModelEvent('message_complete', {})]

    kernel, repo, registry, user, _model = setup_kernel(
        tmp_path, None, stream_factory=factory)

    async def scenario():
        accepted = await kernel.submit('s1', 'main', {'text': '探测'},
                                       wait=False)
        # accept 之后安装 v2 并 reload：运行中的 operation 不得受影响
        write_skill(user, 'probe-skill', '2.0.0',
                    capabilities=['local_readonly'], tools=[probe_tool()],
                    config={'reply': 'v2回复'})
        registry.reload()
        assert registry.resolve('probe-skill').manifest.version == '2.0.0'
        gate.set()
        await kernel.wait(accepted.operation_id)
        return accepted

    accepted = run(scenario())
    assert repo.get_operation(accepted.operation_id).status == 'completed'
    results = [e for e in repo.entries('s1', 'main')
               if e.entry_type == 'tool_result']
    assert results and results[-1].payload['content'] == 'v1回复', \
        '运行中 Skill 更新不得影响该 Operation'


def _crashed_operation(repo, tool_registry, skill='probe-skill'):
    """模拟进程崩溃后的持久化状态：running operation + 已落库的资源快照。"""
    _tools, snapshot = tool_registry.resolve_for_operation(skill_ids=[skill])
    operation = repo.begin_operation('s1', 'main', user_text='断点续跑',
                                     request_id='r-crash')
    repo.set_resource_snapshot(operation.id, snapshot)
    return operation


def test_resume_uses_original_pinned_version(tmp_path):
    kernel, repo, registry, user, _model = setup_kernel(
        tmp_path, tool_then_text_scripts())
    tool_registry = make_tool_registry(registry, executors={'echo': echo_executor})
    operation = _crashed_operation(repo, tool_registry)
    run(kernel.recover('s1'))
    assert repo.get_operation(operation.id).status == 'unknown'
    # 升级到 v2 后恢复：必须使用快照中的 v1
    write_skill(user, 'probe-skill', '2.0.0',
                capabilities=['local_readonly'], tools=[probe_tool()],
                config={'reply': 'v2回复'})
    registry.reload()
    run(kernel.resume(operation.id))
    record = repo.get_operation(operation.id)
    assert record.status == 'completed'
    results = [e for e in repo.entries('s1', 'main')
               if e.entry_type == 'tool_result']
    assert results and results[-1].payload['content'] == 'v1回复', \
        '恢复任务必须使用快照原版本'


def test_resume_without_original_version_fails_without_rerun(tmp_path):
    kernel, repo, registry, user, model = setup_kernel(
        tmp_path, tool_then_text_scripts())
    tool_registry = make_tool_registry(registry, executors={'echo': echo_executor})
    operation = _crashed_operation(repo, tool_registry)
    run(kernel.recover('s1'))
    # 删除原版本、只留 v2：恢复必须失败，不得换版本重跑
    shutil.rmtree(user / 'probe-skill' / '1.0.0')
    write_skill(user, 'probe-skill', '2.0.0',
                capabilities=['local_readonly'], tools=[probe_tool()],
                config={'reply': 'v2回复'})
    registry.reload()
    with pytest.raises(ResourceVersionChanged):
        run(kernel.resume(operation.id))
    record = repo.get_operation(operation.id)
    assert record.status == 'failed'
    assert record.error_code == 'resource.version_changed'
    assert model.requests == [], '找不到原版本时不得发起任何模型请求'


def test_resume_rejects_non_unknown_operation(tmp_path):
    kernel, repo, registry, _user, _model = setup_kernel(
        tmp_path, text_script())
    tool_registry = make_tool_registry(registry, executors={'echo': echo_executor})
    operation = _crashed_operation(repo, tool_registry)
    with pytest.raises(ValueError, match='unknown'):
        run(kernel.resume(operation.id))
