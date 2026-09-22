"""S5-01 文件导入事务化：预检查→staging→hash 校验→原子移动→manifest（先红后绿）。

任何环节失败都不得出现孤儿正式文件，staging 不得残留。
"""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from test_file_service import write_source

from asset_based_agent.report_review_app.repositories.project_repository import (
    ProjectRepository,
)
from asset_based_agent.report_review_app.services.file_service import (
    FileImportService,
)


def _setup(tmp_path, count=10):
    repository = ProjectRepository(tmp_path / 'projects')
    project = repository.create('事务化项目')
    sources = [
        write_source(tmp_path / 'src' / f'f{i:02d}.docx', f'content-{i}'.encode())
        for i in range(count)
    ]
    return repository, project, sources


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


def _assert_clean(project, repository):
    assert _official_files(project) == [], '不允许孤儿正式文件'
    assert _staging_leftovers(project) == [], 'staging 不得残留'
    assert repository.get(project.project_id).files == [], \
        'manifest 不得登记未落地的文件'


@pytest.mark.parametrize('fail_at', [2, 5, 10])
def test_copy_failure_at_nth_file_leaves_no_orphans(
        tmp_path, monkeypatch, fail_at):
    """第 2/5/10 个文件复制失败：整批回滚。"""
    repository, project, sources = _setup(tmp_path)
    original_copy2 = shutil.copy2
    calls = {'n': 0}

    def flaky_copy2(src, dst, *args, **kwargs):
        calls['n'] += 1
        if calls['n'] == fail_at:
            raise OSError('copy boom')
        return original_copy2(src, dst, *args, **kwargs)

    monkeypatch.setattr(shutil, 'copy2', flaky_copy2)
    with pytest.raises(OSError):
        FileImportService(repository).import_files(
            project, sources, round_number=1)
    _assert_clean(project, repository)


def test_invalid_replacement_rejected_before_any_copy(tmp_path):
    """replacement target 未注册：预验证拒绝，不得先复制再报错。"""
    repository, project, sources = _setup(tmp_path, count=3)
    with pytest.raises(ValueError, match='replacement'):
        FileImportService(repository).import_files(
            project, sources, round_number=1,
            replacement_overrides={str(sources[1].resolve()): 'FILE-MISSING'})
    _assert_clean(project, repository)


def test_disk_full_during_copy_leaves_no_orphans(tmp_path, monkeypatch):
    repository, project, sources = _setup(tmp_path, count=4)

    def full_copy2(*args, **kwargs):
        raise OSError(28, 'No space left on device')

    monkeypatch.setattr(shutil, 'copy2', full_copy2)
    with pytest.raises(OSError):
        FileImportService(repository).import_files(
            project, sources, round_number=1)
    _assert_clean(project, repository)


def test_hash_mismatch_rolls_back_entire_batch(tmp_path, monkeypatch):
    """staging hash 校验失败：已复制/已移动的文件全部回滚。"""
    repository, project, sources = _setup(tmp_path, count=3)
    original_copy2 = shutil.copy2

    def corrupting_copy2(src, dst, *args, **kwargs):
        original_copy2(src, dst, *args, **kwargs)
        Path(dst).write_bytes(b'corrupted')

    monkeypatch.setattr(shutil, 'copy2', corrupting_copy2)
    with pytest.raises(OSError, match='verification'):
        FileImportService(repository).import_files(
            project, sources, round_number=1)
    _assert_clean(project, repository)


def test_manifest_write_failure_rolls_back_moved_files(tmp_path, monkeypatch):
    """manifest 写入失败：已原子移动到正式目录的文件必须回滚删除。"""
    repository, project, sources = _setup(tmp_path, count=3)

    def boom_save(project):
        raise RuntimeError('manifest write failure')

    monkeypatch.setattr(repository, 'save', boom_save)
    with pytest.raises(RuntimeError, match='manifest'):
        FileImportService(repository).import_files(
            project, sources, round_number=1)
    _assert_clean(project, repository)


def test_same_name_sources_in_one_batch_do_not_collide(tmp_path):
    """同批同名文件：目标名互不相同且全部落地。"""
    repository = ProjectRepository(tmp_path / 'projects')
    project = repository.create('同名项目')
    first = write_source(tmp_path / 'a' / 'report.docx', b'one')
    second = write_source(tmp_path / 'b' / 'report.docx', b'two')
    imported = FileImportService(repository).import_files(
        project, [first, second], round_number=1)
    paths = {item.original_path for item in imported}
    assert len(paths) == 2
    assert all(Path(p).is_file() for p in paths)


def test_successful_import_leaves_no_staging(tmp_path):
    repository, project, sources = _setup(tmp_path, count=3)
    imported = FileImportService(repository).import_files(
        project, sources, round_number=1)
    assert len(imported) == 3
    assert len(_official_files(project)) == 3
    assert _staging_leftovers(project) == []
