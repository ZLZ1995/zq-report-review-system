"""S07：ToolRegistry——Skill 作为一等 Tool 暴露给 Agent Loop。"""
import asyncio

import pytest
from .skill_fixtures import (
    make_registry,
    make_tool_registry,
    probe_tool,
    write_skill,
)

from asset_based_agent.technical_platform.agent_core.contracts import (
    ToolDescriptor,
)
from asset_based_agent.technical_platform.agent_core.errors import (
    ResourceManifestInvalid,
)


def run(coro):
    return asyncio.run(coro)


def test_descriptors_cover_enabled_skill_tools(tmp_path):
    user = tmp_path / 'u'
    write_skill(user, 'alpha', '1.0.0', capabilities=['local_readonly'],
                tools=[probe_tool('probe_a')])
    write_skill(user, 'beta', '1.0.0', capabilities=['local_readonly'],
                tools=[probe_tool('probe_b')])
    registry = make_registry(tmp_path, user=user)
    registry.set_enabled('beta', False)
    tools = make_tool_registry(registry)
    names = [d.name for d in tools.descriptors()]
    assert names == ['probe_a'], 'disabled Skill 的工具不得出现在描述列表'
    assert isinstance(tools.descriptors()[0], ToolDescriptor)


def test_resolve_for_operation_returns_tools_and_snapshot(tmp_path):
    user = tmp_path / 'u'
    write_skill(user, 'alpha', '1.0.0', capabilities=['local_readonly'],
                tools=[probe_tool()], config={'reply': 'v1回复'})
    registry = make_registry(tmp_path, user=user)
    tools_registry = make_tool_registry(registry)
    tools, snapshot = tools_registry.resolve_for_operation()
    assert [t.descriptor.name for t in tools] == ['probe']
    discovered = registry.resolve('alpha')
    assert snapshot == [{
        'id': 'alpha', 'version': '1.0.0',
        'sha256': discovered.content_sha256, 'source': 'user'}]


def test_skill_tool_executes_with_manifest_config(tmp_path):
    user = tmp_path / 'u'
    write_skill(user, 'alpha', '1.0.0', capabilities=['local_readonly'],
                tools=[probe_tool()], config={'reply': '来自配置'})
    registry = make_registry(tmp_path, user=user)
    tools, _snapshot = make_tool_registry(registry).resolve_for_operation()
    result = run(tools[0].execute(None, {'x': 1}, None))
    assert result.status == 'succeeded'
    assert result.content == '来自配置'
    assert result.result == {'x': 1}


def test_resolve_pinned_reconstructs_original_tools(tmp_path):
    user = tmp_path / 'u'
    write_skill(user, 'alpha', '1.0.0', capabilities=['local_readonly'],
                tools=[probe_tool()], config={'reply': 'v1回复'})
    registry = make_registry(tmp_path, user=user)
    tools_registry = make_tool_registry(registry)
    _tools, snapshot = tools_registry.resolve_for_operation()
    write_skill(user, 'alpha', '2.0.0', capabilities=['local_readonly'],
                tools=[probe_tool()], config={'reply': 'v2回复'})
    registry.reload()
    pinned_tools = tools_registry.resolve_pinned(snapshot)
    result = run(pinned_tools[0].execute(None, {}, None))
    assert result.content == 'v1回复', 'pin 恢复必须重建原版本工具'


def test_unknown_executor_rejected(tmp_path):
    user = tmp_path / 'u'
    write_skill(user, 'alpha', '1.0.0', capabilities=['local_readonly'],
                tools=[probe_tool()], executor='不存在的执行器')
    registry = make_registry(tmp_path, user=user)
    with pytest.raises(ResourceManifestInvalid):
        make_tool_registry(registry).resolve_for_operation()


def test_resolve_for_operation_honors_explicit_skill_ids(tmp_path):
    user = tmp_path / 'u'
    write_skill(user, 'alpha', '1.0.0', capabilities=['local_readonly'],
                tools=[probe_tool('probe_a')])
    write_skill(user, 'beta', '1.0.0', capabilities=['local_readonly'],
                tools=[probe_tool('probe_b')])
    registry = make_registry(tmp_path, user=user)
    tools, snapshot = make_tool_registry(
        registry).resolve_for_operation(skill_ids=['beta'])
    assert [t.descriptor.name for t in tools] == ['probe_b']
    assert [entry['id'] for entry in snapshot] == ['beta']
