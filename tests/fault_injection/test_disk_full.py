"""S8-04 故障注入：磁盘满（disk full）。

注入：导入复制阶段 shutil.copy2 抛 OSError(28) → 整批回滚，
无孤儿正式文件、无 staging 残留、manifest 不登记。
"""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from asset_based_agent.report_review_app.repositories.project_repository import (
    ProjectRepository,
)
from asset_based_agent.report_review_app.services.file_service import (
    FileImportService,
)


def _write_source(path: Path, data: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def _official_files(project):
    files_root = Path(project.project_path) / 'files'
    if not files_root.exists():
        return []
    return [p for p in files_root.rglob('*')
            if p.is_file() and '.staging-' not in str(p)]


def _staging_leftovers(project):
    files_root = Path(project.project_path) / 'files'
    if not files_root.exists():
        return []
    return [p for p in files_root.iterdir() if p.name.startswith('.staging-')]


def test_disk_full_during_import_leaves_no_orphans(tmp_path, monkeypatch):
    repository = ProjectRepository(tmp_path / 'projects')
    project = repository.create('磁盘满项目')
    sources = [
        _write_source(tmp_path / 'src' / f'f{i:02d}.docx', f'content-{i}'.encode())
        for i in range(4)
    ]

    def full_copy2(*args, **kwargs):
        raise OSError(28, 'No space left on device')

    monkeypatch.setattr(shutil, 'copy2', full_copy2)
    with pytest.raises(OSError):
        FileImportService(repository).import_files(project, sources, round_number=1)

    assert _official_files(project) == [], '不允许孤儿正式文件'
    assert _staging_leftovers(project) == [], 'staging 不得残留'
    assert repository.get(project.project_id).files == [], \
        'manifest 不得登记未落地的文件'
