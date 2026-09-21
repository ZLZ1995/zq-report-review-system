"""S14 统一工具装配：Skill Registry、业务 Run Harness 与浏览器工具一个入口。

内核不再分别拼装：assemble_agent_tools 返回（工具列表, 资源快照），
工具名冲突直接拒绝（防止模型歧义调用）。
"""
from __future__ import annotations

from ..business_tools import business_tools

BUILTIN_SNAPSHOT_VERSION = 1


def assemble_agent_tools(*, tool_registry=None, skill_ids=None,
                         business_service=None, browser=(), extra=()):
    tools = []
    snapshot = []
    if tool_registry is not None:
        registry_tools, registry_snapshot = \
            tool_registry.resolve_for_operation(skill_ids)
        tools.extend(registry_tools)
        snapshot.extend(registry_snapshot)
    if business_service is not None:
        tools.extend(business_tools(business_service))
        snapshot.append({'id': 'business.run_harness', 'kind': 'builtin',
                         'version': BUILTIN_SNAPSHOT_VERSION})
    browser = list(browser or ())
    if browser:
        tools.extend(browser)
        snapshot.append({'id': 'browser.tools', 'kind': 'builtin',
                         'version': BUILTIN_SNAPSHOT_VERSION})
    tools.extend(extra or ())
    names = [tool.descriptor.name for tool in tools]
    duplicates = sorted({name for name in names if names.count(name) > 1})
    if duplicates:
        raise ValueError(f'工具名冲突: {", ".join(duplicates)}')
    return tools, snapshot
