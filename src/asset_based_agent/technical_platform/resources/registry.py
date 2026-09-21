"""SkillRegistry：overlay 解析、enable/disable、篡改检测、版本 pin。

信任模型（无签名基础设施下的 TOFU）：首次发现/安装时把内容指纹记入
state 文件；之后每次 reload 重新计算指纹，与登记值不符即判篡改并
拒绝解析。disable 只影响新任务解析，按 pin 恢复（resolve_pinned）
不受影响——中断任务永远有权找到它的原版本。
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from ..agent_core.errors import (
    InvalidRequest,
    ResourceDisabled,
    ResourceTampered,
    ResourceVersionChanged,
)
from .loader import SOURCE_PRECEDENCE, DiscoveredSkill, ResourceLoader
from .zip_install import install_skill_zip


def _version_key(version: str) -> tuple:
    return tuple(int(part) for part in version.split('.'))


class SkillRegistry:
    def __init__(self, *, loader: ResourceLoader, state_path) -> None:
        self.loader = loader
        self.state_path = Path(state_path)
        self._discovered: list[DiscoveredSkill] = []
        self._diagnostics: list[dict] = []
        self._tampered: set[tuple[str, str]] = set()
        self._state = self._load_state()
        self.reload()

    # ------------------------------------------------------------- 状态

    def _load_state(self) -> dict:
        if self.state_path.is_file():
            try:
                data = json.loads(
                    self.state_path.read_text(encoding='utf-8'))
                if isinstance(data, dict) and isinstance(
                        data.get('skills'), dict):
                    return data
            except (OSError, ValueError):
                pass
        return {'skills': {}}

    def _save_state(self) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.state_path.with_suffix(
            self.state_path.suffix + '.tmp')
        temporary.write_text(
            json.dumps(self._state, ensure_ascii=False, indent=2),
            encoding='utf-8')
        os.replace(temporary, self.state_path)

    def _skill_state(self, skill_id: str) -> dict:
        return self._state['skills'].setdefault(
            skill_id, {'enabled': True, 'versions': {}})

    # ------------------------------------------------------------- 扫描

    def reload(self) -> list[dict]:
        discovered, diagnostics = self.loader.discover()
        self._discovered = discovered
        self._tampered = set()
        changed = False
        for skill in discovered:
            manifest = skill.manifest
            state = self._skill_state(manifest.skill_id)
            recorded = state['versions'].get(manifest.version)
            if recorded is None:
                state['versions'][manifest.version] = skill.content_sha256
                changed = True
            elif recorded != skill.content_sha256:
                self._tampered.add((manifest.skill_id, manifest.version))
                diagnostics.append({
                    'path': str(skill.root), 'status': 'tampered',
                    'message': '内容指纹与登记值不符，疑似篡改'})
        if changed:
            self._save_state()
        self._diagnostics = diagnostics
        return diagnostics

    def discovered(self) -> list[DiscoveredSkill]:
        return list(self._discovered)

    def diagnostics(self) -> list[dict]:
        return list(self._diagnostics)

    # ------------------------------------------------------------- 解析

    def _candidates(self, skill_id: str) -> list[DiscoveredSkill]:
        return sorted(
            (d for d in self._discovered
             if d.manifest.skill_id == skill_id),
            key=lambda d: (SOURCE_PRECEDENCE[d.source],
                           _version_key(d.manifest.version)),
            reverse=True)

    def _check_tampered(self, skill: DiscoveredSkill) -> None:
        key = (skill.manifest.skill_id, skill.manifest.version)
        if key in self._tampered:
            raise ResourceTampered(
                f'Skill 内容已被篡改，拒绝使用: {key[0]} {key[1]}')

    def resolve(self, skill_id: str) -> DiscoveredSkill:
        """解析当前生效版本（overlay 优先级 + 源内最高版本）。"""
        candidates = self._candidates(skill_id)
        if not candidates:
            raise InvalidRequest(f'未知 Skill: {skill_id}')
        if not self.is_enabled(skill_id):
            raise ResourceDisabled(f'Skill 已停用: {skill_id}')
        active = candidates[0]
        self._check_tampered(active)
        return active

    def resolve_pinned(self, skill_id: str, version: str,
                       sha256: str) -> DiscoveredSkill:
        """按快照 pin 恢复原版本；找不到版本→ResourceVersionChanged，
        指纹不符→ResourceTampered；不受 disable 影响。"""
        for skill in self._candidates(skill_id):
            if skill.manifest.version != version:
                continue
            self._check_tampered(skill)
            if skill.content_sha256 != sha256:
                raise ResourceTampered(
                    f'Skill {skill_id} {version} 的内容指纹与快照不符')
            return skill
        raise ResourceVersionChanged(
            f'找不到 Skill {skill_id} 的原版本 {version}，任务不得换版本重跑')

    def active_skills(self) -> list[DiscoveredSkill]:
        result = []
        for skill_id in sorted({d.manifest.skill_id
                                for d in self._discovered}):
            try:
                result.append(self.resolve(skill_id))
            except (ResourceDisabled, ResourceTampered):
                continue
        return result

    # ------------------------------------------------------- enable/list

    def is_enabled(self, skill_id: str) -> bool:
        return bool(self._state['skills'].get(skill_id, {}).get(
            'enabled', True))

    def set_enabled(self, skill_id: str, enabled: bool) -> None:
        self._skill_state(skill_id)['enabled'] = bool(enabled)
        self._save_state()

    def list_skills(self) -> list[dict]:
        rows = []
        for skill_id in sorted({d.manifest.skill_id
                                for d in self._discovered}):
            candidates = self._candidates(skill_id)
            enabled = self.is_enabled(skill_id)
            active = None
            if enabled:
                try:
                    active = self.resolve(skill_id)
                except (ResourceDisabled, ResourceTampered):
                    active = None
            shown = active or candidates[0]
            rows.append({
                'id': skill_id,
                'version': shown.manifest.version,
                'name': shown.manifest.name,
                'description': shown.manifest.description,
                'enabled': enabled,
                'source': shown.source,
                'capabilities': list(shown.manifest.capabilities),
                'tampered': any(
                    (skill_id, d.manifest.version) in self._tampered
                    for d in candidates),
                'versions': sorted({d.manifest.version
                                    for d in candidates}, key=_version_key),
            })
        return rows

    # ------------------------------------------------------------- 安装

    def install_zip(self, zip_path) -> DiscoveredSkill:
        if self.loader.user_root is None:
            raise InvalidRequest('未配置用户 Skill 目录，无法安装')
        skill_id, version = install_skill_zip(
            zip_path, self.loader.user_root)
        self.reload()
        for skill in self._candidates(skill_id):
            if skill.manifest.version == version:
                return skill
        raise InvalidRequest(  # pragma: no cover - 安装后必然可发现
            f'安装后未能发现 Skill: {skill_id} {version}')
