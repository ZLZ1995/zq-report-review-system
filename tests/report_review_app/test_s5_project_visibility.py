"""S5-03 损坏项目可见：list() 不得吞掉损坏项目（先红后绿）；
S5-04 interrupted 状态必须有明确出边。
"""
from __future__ import annotations

from asset_based_agent.report_review_app.repositories.project_repository import (
    ProjectRepository,
)
from asset_based_agent.report_review_app.services.project_service import (
    ProjectService,
)


def _corrupt(project_root, dirname='broken-project'):
    broken = project_root / dirname
    broken.mkdir(parents=True)
    (broken / 'project.json').write_text('{invalid json', encoding='utf-8')
    return broken


def test_corrupted_project_listed_with_corrupted_status(tmp_path):
    repository = ProjectRepository(tmp_path / 'projects')
    good = repository.create('正常项目')
    broken = _corrupt(repository.projects_root)

    entries = repository.list()
    corrupted = [entry for entry in entries
                 if getattr(entry, 'status', None) == 'corrupted']
    assert len(corrupted) == 1, '损坏项目必须可见而不是消失'
    entry = corrupted[0]
    assert entry.error == 'manifest_invalid'
    assert str(broken) in entry.path or entry.path == str(broken)
    healthy = [entry for entry in entries
               if getattr(entry, 'status', None) != 'corrupted']
    assert [item.project_id for item in healthy] == [good.project_id]


def test_project_service_passes_corrupted_entries_through(tmp_path):
    service = ProjectService(ProjectRepository(tmp_path / 'projects'))
    service.create_project('正常项目')
    _corrupt(service.repository.projects_root)
    entries = service.list_projects()
    assert any(getattr(entry, 'status', None) == 'corrupted'
               for entry in entries)


def test_unreadable_manifest_file_also_visible(tmp_path):
    repository = ProjectRepository(tmp_path / 'projects')
    broken = _corrupt(repository.projects_root, 'broken-bytes')
    broken.joinpath('project.json').write_bytes(b'\xff\xfe\x00binary')
    entries = repository.list()
    assert any(getattr(entry, 'status', None) == 'corrupted'
               and 'broken-bytes' in entry.path for entry in entries)
