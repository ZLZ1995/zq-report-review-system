"""S14 统一工具装配：Skill Registry、业务 Run Harness 与浏览器工具一个入口。

内核不再分别拼装：assemble_agent_tools 返回（工具列表, 资源快照），
工具名冲突直接拒绝（防止模型歧义调用）。
"""
from __future__ import annotations

from ..business_tools import business_tools

BUILTIN_SNAPSHOT_VERSION = 1


class CompositeToolResolver:
    """Pin Skill resources while rebuilding per-operation builtin tools.

    Builtins are injected by the application (business harness and the bound
    browser backend); Skills remain version-pinned through ``ToolRegistry``.
    This prevents the kernel from seeing one catalog while the model request
    is executed against another catalog.
    """

    def __init__(self, *, tool_registry=None, business_service=None,
                 browser=(), extra=()):
        self.tool_registry = tool_registry
        self.business_service = business_service
        self.browser = tuple(browser or ())
        self.extra = tuple(extra or ())

    def resolve_for_operation(self, skill_ids=None):
        return assemble_agent_tools(
            tool_registry=self.tool_registry, skill_ids=skill_ids,
            business_service=self.business_service, browser=self.browser,
            extra=self.extra)

    def resolve_pinned(self, snapshot):
        skill_snapshot = [entry for entry in (snapshot or [])
                          if entry.get('kind') != 'builtin']
        tools = []
        if self.tool_registry is not None and skill_snapshot:
            tools.extend(self.tool_registry.resolve_pinned(skill_snapshot))
        builtin, _ = assemble_agent_tools(
            business_service=self.business_service, browser=self.browser,
            extra=self.extra)
        tools.extend(builtin)
        names = [tool.descriptor.name for tool in tools]
        if len(names) != len(set(names)):
            raise ValueError('恢复时工具名冲突')
        return tools


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
