import pytest

from asset_based_agent.technical_platform.skills import digest
from asset_based_agent.technical_platform.store import PlatformStore


def fileset(tmp_path):
    store = PlatformStore(tmp_path / 'db.sqlite', 'alice')
    project = store.create_project('synthetic')
    session = store.create_session(project)
    for folder in ('one', 'two'):
        root = tmp_path / folder
        root.mkdir()
        path = root / '报告.docx'
        path.write_bytes(folder.encode())
        store.add_file(project, path, digest(path))
    return store, project, session, store.files(project)


def test_scope_freezes_roles_and_does_not_include_other_project_files(tmp_path):
    from asset_based_agent.technical_platform.file_scope import freeze_scope
    store, project, session, files = fileset(tmp_path)
    scope = freeze_scope(store, session, targets=[files[0]], excluded=[files[1]], revision=1)
    data = scope.to_snapshot()
    assert data['owner'] == 'alice' and data['project_id'] == project
    assert data['session_id'] == session
    assert data['targets'] == [{'id': files[0]['id'], 'sha256': files[0]['sha256']}]
    assert data['excluded'][0]['id'] == files[1]['id']
    assert data['references'] == []
    assert 'path' not in str(data)
    data['targets'].clear()
    assert len(scope.to_snapshot()['targets']) == 1


def test_scope_rejects_overlap_unknown_and_changed_records(tmp_path):
    from asset_based_agent.technical_platform.file_scope import freeze_scope
    store, _, session, files = fileset(tmp_path)
    for kwargs in ({'references': [files[0]]}, {'excluded': [files[0]]}):
        with pytest.raises(ValueError):
            freeze_scope(store, session, targets=[files[0]], revision=1, **kwargs)
    for changed in ({**files[0], 'sha256': '0' * 64}, {**files[0], 'id': 'unknown'}):
        with pytest.raises(PermissionError):
            freeze_scope(store, session, targets=[changed], revision=1)
    with pytest.raises(PermissionError):
        freeze_scope(PlatformStore(store.path, 'bob'), session, targets=[files[0]], revision=1)


@pytest.mark.parametrize('revision', [True, 0, -1, '1'])
def test_scope_rejects_invalid_revision(tmp_path, revision):
    from asset_based_agent.technical_platform.file_scope import freeze_scope
    store, _, session, files = fileset(tmp_path)
    with pytest.raises(ValueError):
        freeze_scope(store, session, targets=[files[0]], revision=revision)

