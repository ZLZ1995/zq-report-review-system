import pytest


def make_preferences(tmp_path):
    from asset_based_agent.technical_platform.storage_preferences import (
        StoragePreferences,
    )
    program = tmp_path / 'program'
    program.mkdir()
    data = tmp_path / 'data'
    data.mkdir()
    return StoragePreferences(tmp_path / 'index.sqlite', program), program, data


def test_root_is_remembered_per_account_without_creation_on_read(tmp_path):
    from asset_based_agent.technical_platform.storage_preferences import (
        StoragePreferences,
    )
    preferences, program, data = make_preferences(tmp_path)
    assert preferences.load('alice') is None
    preferences.select('alice', data)
    reopened = StoragePreferences(preferences.index_path, program)
    assert reopened.load('alice').data_root == data.resolve()
    assert reopened.load('bob') is None
    assert not (data / '.zq-platform').exists()


def test_missing_saved_root_fails_without_fallback(tmp_path):
    preferences, _, data = make_preferences(tmp_path)
    preferences.select('alice', data)
    data.rename(tmp_path / 'unplugged')
    with pytest.raises(OSError):
        preferences.load('alice')
    assert not data.exists()


def test_cannot_silently_switch_root_and_abandon_existing_data(tmp_path):
    preferences, _, data = make_preferences(tmp_path)
    preferences.select('alice', data)
    other = tmp_path / 'other'
    other.mkdir()
    with pytest.raises(ValueError, match='迁移'):
        preferences.select('alice', other)
    assert preferences.load('alice').data_root == data.resolve()


def test_root_validation_precedes_saving_preference(tmp_path):
    preferences, program, _ = make_preferences(tmp_path)
    with pytest.raises(ValueError):
        preferences.select('alice', program)
    assert preferences.load('alice') is None


def test_window_prompts_only_on_first_storage_use(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QApplication

    from asset_based_agent.technical_platform import app as platform
    from asset_based_agent.technical_platform.store import PlatformStore
    qt = QApplication.instance() or QApplication([])
    assert qt
    preferences, _, data = make_preferences(tmp_path)
    calls = []
    monkeypatch.setattr(platform.QFileDialog, 'getExistingDirectory',
                        lambda *a: calls.append('prompt') or str(data))
    window = platform.PlatformWindow(PlatformStore(tmp_path / 'project.sqlite', 'alice'),
                                     storage_preferences=preferences)
    try:
        assert calls == []
        assert window.ensure_storage_layout().data_root == data.resolve()
        assert window.ensure_storage_layout().data_root == data.resolve()
        assert calls == ['prompt']
        data.rename(tmp_path / 'removed-disk')
        assert window.ensure_storage_layout() is None
        assert calls == ['prompt']
        assert not data.exists()
        assert '不会回落系统盘' in window.status.text()
    finally:
        window.close()
