"""Prepare a signed update for the independent managed-installation updater."""

from __future__ import annotations

import hashlib
import json
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .storage_layout import StorageLayout
from .updates.coordinator import PreparedUpdate, prepare_update
from .updates.launcher import load_policy
from .updates.manifest import version_tuple


@dataclass(frozen=True)
class StagedUpdateRequest:
    executable: Path
    command: tuple[str, ...]
    manifest: Path
    package: Path
    inventory: Path


def available_release(info: dict, current_version: str) -> dict | None:
    record = info.get('current_release') if isinstance(info, dict) else None
    if not isinstance(record, dict) or record.get('status') != 'stable':
        return None
    version = record.get('version')
    manifest = record.get('manifest')
    if (not isinstance(version, str) or not isinstance(manifest, dict) or
            version_tuple(version) <= version_tuple(current_version)):
        return None
    payload = manifest.get('payload')
    if (not isinstance(payload, dict) or payload.get('version') != version or
            payload.get('sequence') != record.get('sequence')):
        raise ValueError('服务端更新元数据不一致')
    return record


def _manifest_bytes(record: dict) -> bytes:
    manifest = record.get('manifest')
    digest = record.get('manifest_sha256')
    if not isinstance(manifest, dict) or not isinstance(digest, str):
        raise TypeError('服务端更新清单无效')
    raw = json.dumps(
        manifest, sort_keys=True, separators=(',', ':'),
        ensure_ascii=True, allow_nan=False,
    ).encode('ascii')
    if hashlib.sha256(raw).hexdigest() != digest:
        raise ValueError('服务端更新清单摘要不一致')
    return raw


def stage_update_request(
        record: dict, *, installation_root: Path | None, layout: StorageLayout,
        databases: tuple[Path, ...], now: int, process_id: int,
        prepare: Callable[..., PreparedUpdate] = prepare_update,
) -> StagedUpdateRequest:
    if installation_root is None:
        raise ValueError('当前客户端尚未纳入托管更新，请先使用托管安装包接管。')
    root = installation_root.resolve()
    if root != installation_root or not root.is_dir():
        raise ValueError('托管安装目录不可用')
    updater = root / 'ZQ技术平台更新器.exe'
    if updater.resolve() != updater or not updater.is_file():
        raise ValueError('独立更新器不存在，请修复托管安装。')
    normalized = tuple(path.resolve() for path in databases)
    if (not normalized or len(set(normalized)) != len(normalized) or
            any(path != original or not path.is_file()
                for path, original in zip(normalized, databases, strict=True))):
        raise ValueError('更新前必须提供完整且可用的历史数据库清单')
    raw = _manifest_bytes(record)
    policy = load_policy(root)
    prepared = prepare(raw, layout=layout, policy=policy, now=now)
    attempt = prepared.directory.parent
    staging = layout.update_staging.resolve()
    if (attempt.resolve() != attempt or not attempt.is_relative_to(staging) or
            prepared.directory != attempt / 'ready'):
        raise ValueError('更新暂存目录越界')
    manifest_path = attempt / 'signed-manifest.json'
    inventory_path = attempt / 'database-inventory.json'
    package = attempt / 'package.partial'
    if not package.is_file():
        raise FileNotFoundError('更新包未完整暂存')
    with manifest_path.open('xb') as output:
        output.write(raw)
    with inventory_path.open('x', encoding='utf-8') as output:
        json.dump([str(path) for path in normalized], output, ensure_ascii=False)
    command = (
        str(updater), 'install', '--installation-root', str(root),
        '--manifest', str(manifest_path), '--package', str(package),
        '--databases', str(inventory_path), '--wait-pid', str(process_id),
    )
    return StagedUpdateRequest(
        executable=updater, command=command, manifest=manifest_path,
        package=package, inventory=inventory_path,
    )


def launch_staged_update(request: StagedUpdateRequest) -> None:
    subprocess.Popen(
        request.command,
        cwd=request.executable.parent,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=True,
        creationflags=(getattr(subprocess, 'DETACHED_PROCESS', 0) |
                       getattr(subprocess, 'CREATE_NEW_PROCESS_GROUP', 0)),
    )
