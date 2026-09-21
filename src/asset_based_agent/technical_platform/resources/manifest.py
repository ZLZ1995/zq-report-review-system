"""Skill manifest 结构与校验。

能力规则（计划书 S07 运行时规则）：
- capabilities 必须来自固定目录（与 ToolDescriptor.risk 同一 TOOL_RISKS）；
- 每个声明工具的 risk 必须被 capabilities 显式覆盖——Skill 不能通过
  声明工具隐式获得未声明的能力，更不能借此绕过 PolicyEngine（S09）；
- manifest 只声明意图，授权由 PolicyEngine 在运行时裁决。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..agent_core.contracts import TOOL_RISKS
from ..agent_core.errors import ResourceManifestInvalid

SCHEMA_VERSION = 1
_ID_PATTERN = re.compile(r'^[a-z0-9][a-z0-9-]{1,63}$')
_VERSION_PATTERN = re.compile(r'^\d+\.\d+\.\d+$')
_TOOL_NAME_PATTERN = re.compile(r'^[a-zA-Z][a-zA-Z0-9_]{0,63}$')


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    input_schema: dict
    risk: str = 'local_readonly'


@dataclass(frozen=True)
class SkillManifest:
    skill_id: str
    version: str
    name: str
    description: str = ''
    capabilities: tuple = ()
    tools: tuple = ()
    executor: str = ''
    config: dict = field(default_factory=dict)


def parse_manifest(data, *, source: str = '') -> SkillManifest:
    where = f'（{source}）' if source else ''

    def fail(message):
        raise ResourceManifestInvalid(f'Skill manifest 无效{where}：{message}')

    if not isinstance(data, dict):
        fail('manifest 必须是对象')
    if data.get('schema_version') != SCHEMA_VERSION:
        fail(f'schema_version 必须是 {SCHEMA_VERSION}')
    skill_id = data.get('id')
    if not isinstance(skill_id, str) or not _ID_PATTERN.match(skill_id):
        fail('id 必须是小写 kebab-case 标识符')
    version = data.get('version')
    if not isinstance(version, str) or not _VERSION_PATTERN.match(version):
        fail('version 必须是 x.y.z 形式')
    name = data.get('name')
    if not isinstance(name, str) or not name.strip():
        fail('name 不能为空')
    description = data.get('description') or ''
    if not isinstance(description, str):
        fail('description 必须是字符串')
    capabilities = data.get('capabilities') or []
    if not isinstance(capabilities, list) or any(
            not isinstance(item, str) for item in capabilities):
        fail('capabilities 必须是字符串数组')
    unknown = sorted(set(capabilities) - set(TOOL_RISKS))
    if unknown:
        fail(f'未知能力: {", ".join(unknown)}')
    declared = set(capabilities)
    raw_tools = data.get('tools') or []
    if not isinstance(raw_tools, list):
        fail('tools 必须是数组')
    tools = []
    for raw in raw_tools:
        tools.append(_parse_tool(raw, declared, fail))
    entry = data.get('entry') or {}
    if not isinstance(entry, dict):
        fail('entry 必须是对象')
    executor = entry.get('executor')
    if not isinstance(executor, str) or not executor.strip():
        fail('entry.executor 不能为空')
    config = entry.get('config') or {}
    if not isinstance(config, dict):
        fail('entry.config 必须是对象')
    return SkillManifest(
        skill_id=skill_id, version=version, name=name.strip(),
        description=description, capabilities=tuple(capabilities),
        tools=tuple(tools), executor=executor.strip(), config=dict(config))


def _parse_tool(raw, declared: set, fail) -> ToolSpec:
    if not isinstance(raw, dict):
        fail('tools 项必须是对象')
    name = raw.get('name')
    if not isinstance(name, str) or not _TOOL_NAME_PATTERN.match(name):
        fail('工具 name 必须是合法标识符')
    description = raw.get('description') or ''
    if not isinstance(description, str):
        fail(f'工具 {name} 的 description 必须是字符串')
    schema = raw.get('input_schema')
    if not isinstance(schema, dict):
        fail(f'工具 {name} 的 input_schema 必须是对象')
    properties = schema.get('properties')
    if properties is not None and not isinstance(properties, dict):
        fail(f'工具 {name} 的 input_schema.properties 必须是对象')
    required = schema.get('required')
    if required is not None and (
            not isinstance(required, list)
            or any(type(item) is not str for item in required)):
        fail(f'工具 {name} 的 input_schema.required 必须是字符串数组')
    risk = raw.get('risk', 'local_readonly')
    if risk not in TOOL_RISKS:
        fail(f'工具 {name} 的 risk 非法: {risk}')
    if risk not in declared:
        fail(f'工具 {name} 的 risk（{risk}）未被 capabilities 声明覆盖')
    return ToolSpec(name=name, description=description,
                    input_schema=dict(schema), risk=risk)
