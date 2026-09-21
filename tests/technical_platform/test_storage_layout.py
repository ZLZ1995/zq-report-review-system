"""Explicit non-system storage boundaries, never inferred from a user name."""
from pathlib import Path

import pytest


def roots(tmp_path):
    program, data = tmp_path / 'program', tmp_path / 'data'
    program.mkdir()
    data.mkdir()
    return program, data


def test_layout_requires_existing_root_and_never_recreates_missing_data(tmp_path):
    from asset_based_agent.technical_platform.storage_layout import StorageLayout
    program, data = roots(tmp_path)
    layout = StorageLayout(program, data, 'alice')
    data.rename(tmp_path / 'moved')
    with pytest.raises(OSError):
        layout.prepare()
    assert not data.exists()


def test_layout_separates_accounts_and_is_stable_across_program_versions(tmp_path):
    from asset_based_agent.technical_platform.storage_layout import StorageLayout
    program, data = roots(tmp_path)
    first = StorageLayout(program, data, 'alice/../unsafe')
    second = StorageLayout(program, data, 'bob')
    first.prepare()
    assert first.credentials != second.credentials
    assert first.credentials.is_relative_to(data)
    assert 'unsafe' not in str(first.credentials)
    new_program = tmp_path / 'new-version'
    new_program.mkdir()
    assert StorageLayout(new_program, data, 'alice/../unsafe').credentials == first.credentials
    assert first.cache.is_dir() and first.downloads.is_dir()


def test_layout_allows_platform_data_inside_program_directory(tmp_path):
    from asset_based_agent.technical_platform.storage_layout import StorageLayout
    program, _ = roots(tmp_path)
    nested = program / 'data'
    nested.mkdir()
    assert StorageLayout(program, nested, 'alice').data_root == nested.resolve()


def test_layout_allows_program_directory_inside_platform_root(tmp_path):
    from asset_based_agent.technical_platform.storage_layout import StorageLayout
    _, data = roots(tmp_path)
    nested = data / 'program'
    nested.mkdir()
    assert StorageLayout(nested, data, 'alice').program_root == nested.resolve()


def test_layout_allows_system_drive_for_platform_state(tmp_path, monkeypatch):
    from asset_based_agent.technical_platform.storage_layout import StorageLayout
    program, data = roots(tmp_path)
    monkeypatch.setenv('SystemDrive', data.drive)
    assert StorageLayout(program, data, 'alice').data_root == data.resolve()


def test_layout_rejects_empty_account(tmp_path):
    from asset_based_agent.technical_platform.storage_layout import StorageLayout
    program, data = roots(tmp_path)
    with pytest.raises(ValueError):
        StorageLayout(program, data, ' ')


def test_layout_rejects_link_to_another_account_inside_same_root(tmp_path, monkeypatch):
    from asset_based_agent.technical_platform.storage_layout import StorageLayout
    program, data = roots(tmp_path)
    alice = StorageLayout(program, data, 'alice')
    bob = StorageLayout(program, data, 'bob')
    source, other = alice.credentials, bob.credentials
    original = Path.resolve
    monkeypatch.setattr(Path, 'resolve',
                        lambda path, *a, **kw: other if path == source else original(path, *a, **kw))
    with pytest.raises(ValueError):
        _ = alice.credentials
