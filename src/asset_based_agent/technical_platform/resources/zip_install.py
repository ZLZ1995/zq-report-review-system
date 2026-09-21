"""Skill zip 安装：结构校验、安全解包、登记。

安全规则：单顶层目录且与 manifest id 一致；拒绝绝对路径、驱动器
前缀与 `..` 穿越；同版本重复安装拒绝（显式卸载后方可重装）。
"""
from __future__ import annotations

import json
import zipfile
from pathlib import Path, PurePosixPath

from ..agent_core.errors import ResourceManifestInvalid
from .manifest import parse_manifest


def install_skill_zip(zip_path, user_root: Path) -> tuple[str, str]:
    """安装技能 zip 到 <user_root>/<id>/<version>/，返回 (id, version)。"""
    with zipfile.ZipFile(zip_path) as archive:
        members = [name for name in archive.namelist()
                   if not name.endswith('/')]
        if not members:
            raise ResourceManifestInvalid('zip 为空')
        for name in members:
            _check_member(name)
        tops = {name.split('/')[0] for name in members}
        if len(tops) != 1:
            raise ResourceManifestInvalid('zip 必须包含且仅包含一个顶层目录')
        top = tops.pop()
        manifest_name = f'{top}/skill.json'
        if manifest_name not in members:
            raise ResourceManifestInvalid('zip 缺少 skill.json')
        try:
            data = json.loads(archive.read(manifest_name).decode('utf-8'))
        except (UnicodeDecodeError, ValueError) as exc:
            raise ResourceManifestInvalid(
                f'zip 内 skill.json 不是合法 JSON: {exc}') from exc
        manifest = parse_manifest(data, source=f'{zip_path}:{manifest_name}')
        if manifest.skill_id != top:
            raise ResourceManifestInvalid(
                'zip 顶层目录名必须与 manifest id 一致')
        target = Path(user_root) / manifest.skill_id / manifest.version
        if target.exists():
            raise FileExistsError(
                f'该 Skill 版本已安装: {manifest.skill_id} {manifest.version}')
        target.mkdir(parents=True)
        for name in members:
            relative = PurePosixPath(name).relative_to(top)
            destination = target / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(archive.read(name))
    return manifest.skill_id, manifest.version


def _check_member(name: str) -> None:
    parts = PurePosixPath(name).parts
    if name.startswith('/') or '..' in parts or parts[0].endswith(':'):
        raise ResourceManifestInvalid(f'zip 包含非法路径: {name}')
