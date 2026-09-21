import os

import pytest

from scripts.windows_file_owners import file_owners


@pytest.mark.skipif(os.name != 'nt', reason='Windows diagnostic')
def test_reports_synthetic_open_file_and_releases_query_session(tmp_path):
    path = tmp_path / 'locked.txt'
    path.write_text('synthetic', encoding='utf-8')
    with path.open('rb'):
        assert os.getpid() in {item['pid'] for item in file_owners([path])}
    assert os.getpid() not in {item['pid'] for item in file_owners([path])}


@pytest.mark.parametrize('kind', ['plain', 'sqlite', 'nested_sqlite', 'store', 'catalog'])
def test_directory_move_without_qt(tmp_path, kind):
    import sqlite3
    from contextlib import closing

    from asset_based_agent.technical_platform.project_catalog import ProjectCatalog
    for index in range(20):
        root = tmp_path / f'project-{index}'
        root.mkdir()
        if kind == 'plain':
            (root / 'data.txt').write_text('synthetic', encoding='utf-8')
        elif kind in {'sqlite', 'nested_sqlite'}:
            data_root = root if kind == 'sqlite' else root / '.zq'
            data_root.mkdir(exist_ok=True)
            with closing(sqlite3.connect(data_root / 'data.sqlite')) as db, db:
                db.execute('CREATE TABLE sample (id INTEGER)')
                db.execute('INSERT INTO sample VALUES(1)')
        elif kind == 'store':
            from asset_based_agent.technical_platform.store import PlatformStore
            store = PlatformStore(root / '.zq' / 'platform.sqlite', 'alice')
            project = store.create_project('project')
            store.create_session(project, 'one')
            store.create_session(project, 'two')
        else:
            catalog = ProjectCatalog(tmp_path / f'index-{index}.sqlite', 'alice')
            project = catalog.create_project('project', root)
            catalog.create_session(project, 'one')
            catalog.create_session(project, 'two')
        try:
            root.rename(tmp_path / f'moved-{index}')
        except PermissionError:
            files = list(root.rglob('*.sqlite'))
            try:
                print('NO_QT_RENAME_FAILURE', kind, index, file_owners(files) if files else [])
            except (OSError, ValueError) as error:
                print('NO_QT_DIAGNOSTIC_ERROR', repr(error))
            raise
