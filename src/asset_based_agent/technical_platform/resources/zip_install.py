"""Skill zip 安装：结构校验、安全解包、原子登记。

安全规则（S4-01）：单顶层目录且与 manifest id 一致；成员名禁止 `\\`、
绝对路径、驱动器前缀、`..`、空段/`.` 段、NUL；拒绝大小写重复路径、
加密条目、符号链接与一切非常规文件；成员数 / 展开总字节 / 单文件
字节 / 压缩比均有上限。解包先到用户目录下的临时 staging 目录，逐成员
做 resolve 包含校验，全部成功后原子 rename 到正式版本目录——
中途任何失败都不留半成品。
"""
from __future__ import annotations

import json
import os
import shutil
import stat
import uuid
import zipfile
from pathlib import Path, PurePosixPath

from ..agent_core.errors import ResourceManifestInvalid
from .manifest import parse_manifest

MAX_MEMBERS = 10_000
MAX_EXPANDED_BYTES = 32 * 1024 * 1024
MAX_MEMBER_BYTES = 8 * 1024 * 1024
MAX_COMPRESSION_RATIO = 100


def install_skill_zip(zip_path, user_root: Path) -> tuple[str, str]:
    """安装技能 zip 到 <user_root>/<id>/<version>/，返回 (id, version)。"""
    user_root = Path(user_root)
    with zipfile.ZipFile(zip_path) as archive:
        infos = [info for info in archive.infolist() if not info.is_dir()]
        if not infos:
            raise ResourceManifestInvalid('zip 为空')
        if len(infos) > MAX_MEMBERS:
            raise ResourceManifestInvalid(
                f'zip 成员数量超过限制（{MAX_MEMBERS}）')
        names = [info.filename for info in infos]
        if len({name.casefold() for name in names}) != len(names):
            raise ResourceManifestInvalid('zip 存在大小写重复路径')
        expanded = 0
        for info in infos:
            _check_member(info)
            if info.file_size > MAX_MEMBER_BYTES:
                raise ResourceManifestInvalid(
                    f'zip 单文件超过大小限制: {info.filename}')
            expanded += info.file_size
        if expanded > MAX_EXPANDED_BYTES:
            raise ResourceManifestInvalid('zip 展开内容超过大小限制')
        tops = {name.split('/')[0] for name in names}
        if len(tops) != 1:
            raise ResourceManifestInvalid('zip 必须包含且仅包含一个顶层目录')
        top = tops.pop()
        manifest_name = f'{top}/skill.json'
        if manifest_name not in names:
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
        target = user_root / manifest.skill_id / manifest.version
        if target.exists():
            raise FileExistsError(
                f'该 Skill 版本已安装: {manifest.skill_id} {manifest.version}')
        staging = user_root / f'.install-{uuid.uuid4().hex}'
        staging_resolved = staging.resolve()
        try:
            staging.mkdir(parents=True)
            for info in infos:
                relative = PurePosixPath(info.filename).relative_to(top)
                destination = staging / relative
                # 写入前校验：目标必须落在 staging 内（防符号链接式穿越）
                resolved = destination.parent.resolve() / destination.name
                if not resolved.is_relative_to(staging_resolved):
                    raise ResourceManifestInvalid(
                        f'zip 包含非法路径: {info.filename}')
                destination.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(info) as source:
                    destination.write_bytes(source.read())
            target.parent.mkdir(parents=True, exist_ok=True)
            os.replace(staging, target)  # 完整校验成功后原子改名
        except BaseException:
            shutil.rmtree(staging, ignore_errors=True)
            raise
    return manifest.skill_id, manifest.version


def _check_member(info: zipfile.ZipInfo) -> None:
    name = info.filename
    if '\\' in name or '\x00' in name:
        raise ResourceManifestInvalid(f'zip 包含非法路径: {name}')
    parts = name.split('/')
    if (name.startswith('/') or parts[0].endswith(':')
            or any(part in {'', '.', '..'} for part in parts)):
        raise ResourceManifestInvalid(f'zip 包含非法路径: {name}')
    if info.flag_bits & 1:
        raise ResourceManifestInvalid('zip 包含加密条目')
    mode = info.external_attr >> 16
    # 无类型位（如 0o600，Python writestr 默认）按普通文件对待；
    # 有类型位则必须是普通文件——符号链接/FIFO/设备等一律拒绝。
    if stat.S_IFMT(mode) and not stat.S_ISREG(mode):
        raise ResourceManifestInvalid(f'zip 包含非常规文件: {name}')
    if (info.file_size >= 4096 and info.compress_size > 0
            and info.file_size > info.compress_size * MAX_COMPRESSION_RATIO):
        raise ResourceManifestInvalid('zip 压缩比异常，疑似 zip bomb')
