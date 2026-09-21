"""S07 资源层：Skill 发现、manifest 校验、overlay、版本快照。

把所有 Skill/Tool 从硬编码路由中移出：Skill 是落盘的声明式资源包
（skill.json + 载荷文件），执行逻辑由应用内固定执行器目录提供，
资源包本身不含可执行代码。
"""
from .loader import DiscoveredSkill, ResourceLoader, content_sha256
from .manifest import SkillManifest, ToolSpec, parse_manifest
from .registry import SkillRegistry

__all__ = [
    'DiscoveredSkill',
    'ResourceLoader',
    'SkillManifest',
    'SkillRegistry',
    'ToolSpec',
    'content_sha256',
    'parse_manifest',
]
