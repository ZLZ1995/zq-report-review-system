from pathlib import Path

import pytest

from asset_based_agent.technical_platform.project_catalog import ProjectCatalog


@pytest.fixture(autouse=True)
def test_drive(monkeypatch):
    monkeypatch.setenv("SystemDrive", "Z:")


def test_index_stores_locations_not_business_and_restores(tmp_path):
    index = tmp_path / "settings" / "index.sqlite"
    root = tmp_path / "business"
    root.mkdir()
    catalog = ProjectCatalog(index, "alice")
    assert catalog.projects() == []
    identity = catalog.create_project("one", root)
    session = catalog.create_session(identity)
    catalog.append(session, "user", "BUSINESS_SECRET")
    catalog.remember_session(session)
    assert b"BUSINESS_SECRET" not in index.read_bytes()
    assert catalog.path.parent == root / ".zq"
    reopened = ProjectCatalog(index, "alice")
    assert reopened.last_project == identity
    reopened.select_project(identity)
    assert reopened.last_session == session
    assert reopened.messages(session)[0]["text"] == "BUSINESS_SECRET"
    assert ProjectCatalog(index, "bob").projects() == []


def test_missing_directory_never_recreated(tmp_path):
    root = tmp_path / "business"
    root.mkdir()
    catalog = ProjectCatalog(tmp_path / "index.sqlite", "alice")
    identity = catalog.create_project("one", root)
    root.rename(tmp_path / "moved")
    assert catalog.projects()[0]["unavailable"]
    with pytest.raises(OSError):
        catalog.select_project(identity)
    assert not root.exists()


def test_open_existing_preserves_files_and_owner_scope(tmp_path):
    from asset_based_agent.technical_platform.store import PlatformStore

    root = tmp_path / "old"
    old = PlatformStore(root / "platform.sqlite", "alice")
    identity = old.create_project("old")
    old.create_session(identity)
    catalog = ProjectCatalog(tmp_path / "index.sqlite", "alice")
    assert catalog.open_directory(root) == [identity]
    assert catalog.open_directory(root) == [identity]
    assert len(catalog.projects()) == 1
    catalog.select_project(identity)
    assert catalog.path == old.path
    assert ProjectCatalog(catalog.index_path, "bob").open_directory(root) == []


def test_system_drive_rejected_for_new_project():
    from asset_based_agent.technical_platform.project_catalog import (
        validate_business_directory,
    )

    with pytest.raises(ValueError):
        validate_business_directory(Path("C:/business"), system_drive="C:")


def test_update_database_inventory_includes_index_and_every_registered_project(tmp_path):
    catalog = ProjectCatalog(tmp_path / 'index.sqlite', 'alice')
    roots = [tmp_path / 'one', tmp_path / 'two']
    for index, root in enumerate(roots):
        root.mkdir()
        catalog.create_project(f'project-{index}', root)
    inventory = catalog.update_database_inventory()
    assert inventory[0] == catalog.index_path.resolve()
    assert set(inventory[1:]) == {
        (root / '.zq/platform.sqlite').resolve() for root in roots
    }


def test_update_database_inventory_blocks_when_historical_project_is_offline(tmp_path):
    root = tmp_path / 'business'
    root.mkdir()
    catalog = ProjectCatalog(tmp_path / 'index.sqlite', 'alice')
    catalog.create_project('project', root)
    root.rename(tmp_path / 'offline')
    with pytest.raises(OSError, match='不可用'):
        catalog.update_database_inventory()
