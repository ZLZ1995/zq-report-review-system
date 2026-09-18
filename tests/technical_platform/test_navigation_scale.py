import sqlite3
import time

import pytest

from asset_based_agent.technical_platform.navigation_snapshot import navigation_snapshot
from asset_based_agent.technical_platform.store import PlatformStore


@pytest.mark.parametrize('catalog_mode', [False, True])
def test_large_navigation_bounds_query_work_and_keeps_all_unread_counts(tmp_path, monkeypatch, catalog_mode):
    store = PlatformStore(tmp_path / 'state.sqlite', 'alice')
    with store.connect() as db:
        db.executemany('INSERT INTO projects VALUES(?,?,?,0,?)',
                       [(f'p{i}', 'alice', f'Project {i}', 'now') for i in range(100)])
        db.executemany('INSERT INTO sessions VALUES(?,?,?,?)',
                       [(f's{i}', f'p{i // 10}', f'Chat {i}', 'now') for i in range(1000)])
        db.executemany('INSERT INTO messages(session,role,text,created) VALUES(?,?,?,?)',
                       [(f's{i}', 'assistant', 'synthetic', 'now') for i in range(1000) for _ in range(20)])
    if catalog_mode:
        from asset_based_agent.technical_platform.project_catalog import ProjectCatalog
        catalog = ProjectCatalog(tmp_path / 'index.sqlite', 'alice')
        with catalog.index() as db:
            db.executemany('INSERT INTO locations(owner,project,name,path,session) VALUES(?,?,?,?,NULL)',
                           [('alice', f'p{i}', f'Project {i}', str(store.path)) for i in range(100)])
        store = catalog
    connect = sqlite3.connect
    operations = 0

    def counted_connect(*args, **kwargs):
        db = connect(*args, **kwargs)
        def progress():
            nonlocal operations
            operations += 1000
            return int(operations > 2_000_000)
        db.set_progress_handler(progress, 1000)
        return db

    monkeypatch.setattr(sqlite3, 'connect', counted_connect)
    started = time.monotonic()
    rows = navigation_snapshot(store)
    elapsed = time.monotonic() - started
    assert len(rows) == 100
    assert sum(len(p['sessions']) for p in rows) == 1000
    assert all(s['unread_count'] == 20 for p in rows for s in p['sessions'])
    print(f'NAVIGATION_SCALE projects=100 sessions=1000 messages=20000 elapsed={elapsed:.3f}s vm_steps={operations}')


def test_grouped_unread_counts_keep_owner_archive_and_read_boundaries(tmp_path):
    from asset_based_agent.technical_platform.session_service import SessionService
    store = PlatformStore(tmp_path / 'state.sqlite', 'alice')
    project = store.create_project('visible')
    session = store.create_session(project, 'visible')
    service = SessionService(store)
    store.append(session, 'assistant', 'already read')
    service.mark_read(session, store.messages(session)[-1]['id'])
    store.append(session, 'user', 'not counted')
    store.append(session, 'assistant', 'unread')
    archived = store.create_session(project, 'archived')
    store.append(archived, 'assistant', 'hidden by archive')
    service.archive(archived, True)
    other = PlatformStore(store.path, 'bob')
    other_project = other.create_project('private')
    other_session = other.create_session(other_project, 'private')
    other.append(other_session, 'assistant', 'never expose')
    rows = navigation_snapshot(store)
    assert [p['id'] for p in rows] == [project]
    assert [s['id'] for s in rows[0]['sessions']] == [session]
    assert rows[0]['sessions'][0]['unread_count'] == 1
