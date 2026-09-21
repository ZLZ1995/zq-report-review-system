"""ToolRegistry：把 SkillRegistry 中的 Skill 暴露为一等 AgentTool。

执行模型：Skill 是声明式资源包（manifest + 配置/提示词），执行逻辑
来自应用内固定的执行器目录（executors，依赖注入）；zip 安装的外部
Skill 只能引用既有执行器，不能携带可执行代码。
"""
from __future__ import annotations

import inspect

from ..agent_core.contracts import ToolDescriptor
from ..agent_core.errors import ResourceManifestInvalid
from ..resources.loader import DiscoveredSkill
from ..resources.registry import SkillRegistry


class SkillTool:
    """单个 Skill 工具声明的 AgentTool 实现。"""

    def __init__(self, discovered: DiscoveredSkill, spec, executor) -> None:
        manifest = discovered.manifest
        self.descriptor = ToolDescriptor(
            name=spec.name, description=spec.description,
            input_schema=spec.input_schema, risk=spec.risk)
        self.skill_id = manifest.skill_id
        self.skill_version = manifest.version
        self.skill_sha256 = discovered.content_sha256
        self._executor = executor
        self._config = dict(manifest.config)

    async def execute(self, context, arguments, cancel):
        result = self._executor(context, arguments, cancel, self._config)
        if inspect.isawaitable(result):
            result = await result
        return result


class ToolRegistry:
    def __init__(self, *, skill_registry: SkillRegistry,
                 executors: dict) -> None:
        self.skills = skill_registry
        self._executors = dict(executors)

    def descriptors(self) -> list[ToolDescriptor]:
        """当前全部启用 Skill 的工具描述（供 UI 列表与模型上下文）。"""
        descriptors: list[ToolDescriptor] = []
        for discovered in self.skills.active_skills():
            for spec in discovered.manifest.tools:
                descriptors.append(ToolDescriptor(
                    name=spec.name, description=spec.description,
                    input_schema=spec.input_schema, risk=spec.risk))
        return descriptors

    def resolve_for_operation(self, skill_ids=None):
        """Operation accept：解析工具并给出可持久化的资源快照。"""
        if skill_ids:
            discovered = [self.skills.resolve(skill_id)
                          for skill_id in skill_ids]
        else:
            discovered = self.skills.active_skills()
        tools = []
        snapshot = []
        for skill in discovered:
            tools.extend(self._build_tools(skill))
            snapshot.append({
                'id': skill.manifest.skill_id,
                'version': skill.manifest.version,
                'sha256': skill.content_sha256,
                'source': skill.source,
            })
        return tools, snapshot

    def resolve_pinned(self, snapshot) -> list[SkillTool]:
        """按快照重建原版本工具；版本缺失/篡改由 SkillRegistry 抛出。"""
        tools = []
        for entry in snapshot or []:
            discovered = self.skills.resolve_pinned(
                entry['id'], entry['version'], entry['sha256'])
            tools.extend(self._build_tools(discovered))
        return tools

    def _build_tools(self, discovered: DiscoveredSkill) -> list[SkillTool]:
        manifest = discovered.manifest
        if not manifest.tools:
            return []
        executor = self._executors.get(manifest.executor)
        if executor is None:
            raise ResourceManifestInvalid(
                f'未知执行器: {manifest.executor}（Skill {manifest.skill_id}）')
        return [SkillTool(discovered, spec, executor)
                for spec in manifest.tools]
