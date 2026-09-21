"""ResourceLoader：内置/用户/项目三源 Skill 发现与内容指纹。

目录约定：``<root>/<skill_id>/<version>/skill.json``（+ 任意载荷文件）。
发现失败（坏 manifest 等）只记诊断，不阻断其他 Skill。
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

from ..agent_core.errors import ResourceManifestInvalid
from .manifest import SkillManifest, parse_manifest

SOURCE_PRECEDENCE = {'project': 3, 'user': 2, 'builtin': 1}


@dataclass(frozen=True)
class DiscoveredSkill:
    manifest: SkillManifest
    source: str  # 'builtin' | 'user' | 'project'
    root: Path   # 版本目录
    content_sha256: str


def content_sha256(version_dir: Path) -> str:
    """版本目录内容指纹：相对路径与各自 sha256 的规范哈希。"""
    entries = []
    for path in sorted(version_dir.rglob('*')):
        if not path.is_file():
            continue
        relative = path.relative_to(version_dir).as_posix()
        digest = sha256(path.read_bytes()).hexdigest()
        entries.append(f'{relative}\0{digest}')
    return sha256('\n'.join(entries).encode('utf-8')).hexdigest()


class ResourceLoader:
    def __init__(self, *, builtin_root=None, user_root=None,
                 project_root=None) -> None:
        self.builtin_root = (Path(builtin_root) if builtin_root
                             else Path(__file__).parent / 'builtin_skills')
        self.user_root = Path(user_root) if user_root else None
        self.project_root = Path(project_root) if project_root else None

    def discover(self) -> tuple[list[DiscoveredSkill], list[dict]]:
        discovered: list[DiscoveredSkill] = []
        diagnostics: list[dict] = []
        for source, root in (('builtin', self.builtin_root),
                             ('user', self.user_root),
                             ('project', self.project_root)):
            if root is None or not root.is_dir():
                continue
            for skill_dir in sorted(p for p in root.iterdir() if p.is_dir()):
                for version_dir in sorted(p for p in skill_dir.iterdir()
                                          if p.is_dir()):
                    skill = self._load_one(source, skill_dir, version_dir,
                                           diagnostics)
                    if skill is not None:
                        discovered.append(skill)
        return discovered, diagnostics

    @staticmethod
    def _load_one(source, skill_dir, version_dir, diagnostics):
        manifest_path = version_dir / 'skill.json'
        if not manifest_path.is_file():
            diagnostics.append({
                'path': str(version_dir), 'status': 'missing_manifest',
                'message': '缺少 skill.json'})
            return None
        try:
            data = json.loads(manifest_path.read_text(encoding='utf-8'))
            manifest = parse_manifest(data, source=str(manifest_path))
        except (ValueError, ResourceManifestInvalid) as exc:
            diagnostics.append({
                'path': str(manifest_path), 'status': 'invalid_manifest',
                'message': str(exc)})
            return None
        if manifest.skill_id != skill_dir.name \
                or manifest.version != version_dir.name:
            diagnostics.append({
                'path': str(manifest_path), 'status': 'id_version_mismatch',
                'message': '目录名必须与 manifest id/version 一致'})
            return None
        return DiscoveredSkill(
            manifest=manifest, source=source, root=version_dir,
            content_sha256=content_sha256(version_dir))
