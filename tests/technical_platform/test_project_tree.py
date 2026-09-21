import os

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from asset_based_agent.technical_platform.app import PlatformWindow
from asset_based_agent.technical_platform.project_catalog import ProjectCatalog


def test_project_tree_expands_multiple_projects_without_switching_store(tmp_path):
    qt = QApplication.instance() or QApplication([])
    catalog = ProjectCatalog(tmp_path / 'index.sqlite', 'alice')
    pairs = []
    for name in ('one', 'two'):
        root = tmp_path / name
        root.mkdir()
        project = catalog.create_project(name, root)
        session = catalog.create_session(project, name + ' chat')
        pairs.append((project, session))
    window = PlatformWindow(catalog)
    try:
        tree = window.project_tree
        assert tree.topLevelItemCount() == 2
        assert catalog.last_project == pairs[1][0]
        for index, pair in enumerate(pairs):
            node = tree.topLevelItem(index)
            node.setExpanded(True)
            assert node.childCount() == 1
            assert node.child(0).data(0, Qt.ItemDataRole.UserRole) == pair
        tree.setCurrentItem(tree.topLevelItem(0).child(0))
        assert (window.project_id, window.session_id) == pairs[0]
        window.composer.setPlainText('draft one')
        tree.setCurrentItem(tree.topLevelItem(1).child(0))
        assert (window.project_id, window.session_id) == pairs[1]
        assert window.composer.toPlainText() == ''
        tree.setCurrentItem(tree.topLevelItem(0).child(0))
        assert window.composer.toPlainText() == 'draft one'
        assert all(tree.topLevelItem(i).isExpanded() for i in range(2))
        assert window.projects.isHidden() and window.sessions.isHidden()
    finally:
        window.close()
    assert qt is not None


def test_tree_new_session_selects_new_chat_in_catalog(tmp_path):
    qt = QApplication.instance() or QApplication([])
    root = tmp_path / 'project'
    root.mkdir()
    catalog = ProjectCatalog(tmp_path / 'index.sqlite', 'alice')
    project = catalog.create_project('project', root)
    old = catalog.create_session(project, 'old')
    catalog.remember_session(old)
    window = PlatformWindow(catalog)
    try:
        window.new_session()
        assert window.session_id != old
        assert window.project_tree.currentItem().data(0, Qt.ItemDataRole.UserRole) == (project, window.session_id)
    finally:
        window.close()
    assert qt is not None


def test_tree_refresh_does_not_initialize_or_migrate_project_stores(tmp_path, monkeypatch):
    from asset_based_agent.technical_platform.store import PlatformStore
    qt = QApplication.instance() or QApplication([])
    root = tmp_path / 'project'
    root.mkdir()
    catalog = ProjectCatalog(tmp_path / 'index.sqlite', 'alice')
    project = catalog.create_project('project', root)
    catalog.create_session(project, 'chat')
    window = PlatformWindow(catalog)
    try:
        def forbidden(*args, **kwargs):
            raise ValueError('Status reads must not initialize a writable store')
        monkeypatch.setattr(PlatformStore, '__init__', forbidden)
        window.refresh_project_tree()
        assert window.project_tree.topLevelItem(0).childCount() == 1
    finally:
        window.close()
    assert qt is not None


def test_tree_background_unread_and_branch_survive_refresh(tmp_path):
    from asset_based_agent.technical_platform.session_service import SessionService
    from asset_based_agent.technical_platform.store import PlatformStore
    qt = QApplication.instance() or QApplication([])
    store = PlatformStore(tmp_path / 'state.sqlite', 'alice')
    project = store.create_project('project')
    first = store.create_session(project, 'first')
    store.append(first, 'assistant', 'completed')
    service = SessionService(store)
    child = service.fork(first, store.messages(first)[-1]['id'], 'branch chat')
    window = PlatformWindow(store)
    window.reload_projects(project)
    window.reload_sessions(first)
    try:
        store.append(child, 'assistant', 'background result')
        window.refresh_session_badges()
        node = window.project_tree.topLevelItem(0)
        labels = [node.child(i).text(0) for i in range(node.childCount())]
        assert any('分支' in label and '未读 1' in label for label in labels)
        assert window.session_id == first
        service.rename(child, 'renamed branch')
        window.refresh_session_badges()
        assert any('renamed branch' in node.child(i).text(0) for i in range(node.childCount()))
        service.archive(child, True)
        window.refresh_session_badges()
        assert node.childCount() == 1
        window.show()
        qt.processEvents()
        assert window.grab().save(str(tmp_path / 'project-tree.png'))
    finally:
        window.close()


def test_locked_background_project_does_not_block_or_change_active_chat(tmp_path):
    import sqlite3
    import time
    from contextlib import closing
    from threading import Event
    from types import SimpleNamespace

    from asset_based_agent.technical_platform.task_manager import TaskBinding
    qt = QApplication.instance() or QApplication([])
    catalog = ProjectCatalog(tmp_path / 'index.sqlite', 'alice')
    pairs = []
    for name in ('background', 'active'):
        root = tmp_path / name
        root.mkdir()
        project = catalog.create_project(name, root)
        session = catalog.create_session(project, name)
        pairs.append((project, session, catalog.active))
    window = PlatformWindow(catalog)
    project, session, source = pairs[0]
    worker = SimpleNamespace(cancel=Event(), isRunning=lambda: True)
    binding = TaskBinding('alice', project, session, 'understanding:background')
    window.task_manager.register(binding, worker)
    try:
        window.composer.setPlainText('preserve active draft')
        source.append(session, 'assistant', 'background result')
        window.refresh_session_badges()
        node = window.project_tree.topLevelItem(0)
        assert '运行中' in node.child(0).text(0) and '未读 1' in node.child(0).text(0)
        with closing(sqlite3.connect(source.path)) as lock:
            lock.execute('BEGIN EXCLUSIVE')
            started = time.monotonic()
            window.refresh_session_badges()
            assert time.monotonic() - started < 2
            assert '暂不可用' in node.text(0)
            assert window.project_tree.topLevelItem(1).childCount() == 1
        window.refresh_session_badges()
        assert node.childCount() == 1 and '未读 1' in node.child(0).text(0)
        with closing(sqlite3.connect(pairs[1][2].path)) as lock:
            lock.execute('BEGIN EXCLUSIVE')
            started = time.monotonic()
            window.refresh_session_badges()
            assert time.monotonic() - started < 2
        assert (window.project_id, window.session_id) == pairs[1][:2]
        assert window.composer.toPlainText() == 'preserve active draft'
    finally:
        worker.isRunning = lambda: False
        window.task_manager.finish(binding, worker)
        window.close()
    assert qt is not None


def test_navigation_does_not_create_missing_database_or_migrate_old_schema(tmp_path):
    import sqlite3
    from contextlib import closing

    from asset_based_agent.technical_platform.navigation_snapshot import (
        navigation_snapshot,
    )
    catalog = ProjectCatalog(tmp_path / 'index.sqlite', 'alice')
    root = tmp_path / 'project'
    root.mkdir()
    project = catalog.create_project('project', root)
    path = catalog.active.path
    with closing(sqlite3.connect(path)) as db:
        db.execute('PRAGMA user_version=5')
    assert navigation_snapshot(catalog)[0]['unavailable']
    with closing(sqlite3.connect(path)) as db:
        assert db.execute('PRAGMA user_version').fetchone()[0] == 5
    assert not (path.parent / 'migration-backups').exists()
    moved = path.with_name('moved.sqlite')
    path.rename(moved)
    assert navigation_snapshot(catalog)[0]['unavailable']
    assert not path.exists()
    assert catalog.last_project == project
