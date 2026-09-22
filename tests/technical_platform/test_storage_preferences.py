import pytest


def make_preferences(tmp_path):
    from asset_based_agent.technical_platform.storage_preferences import (
        StoragePreferences,
    )
    program = tmp_path / 'program'
    program.mkdir()
    data = program / 'data'
    data.mkdir()
    return StoragePreferences(tmp_path / 'index.sqlite', program), program, data


def test_installation_data_root_is_created_and_remembered_per_account(tmp_path):
    from asset_based_agent.technical_platform.storage_preferences import (
        StoragePreferences,
    )
    preferences, program, data = make_preferences(tmp_path)
    assert preferences.load('alice') is None
    layout = preferences.ensure_default('alice')
    assert layout.data_root == (program / 'data').resolve()
    assert layout.data_root.is_dir()
    reopened = StoragePreferences(preferences.index_path, program)
    assert reopened.load('alice').data_root == (program / 'data').resolve()
    assert reopened.load('bob') is None
    assert not (data / '.zq-platform').exists()


def test_agent_permission_mode_is_persisted_per_account(tmp_path):
    from asset_based_agent.technical_platform.storage_preferences import (
        StoragePreferences,
    )

    preferences, program, _ = make_preferences(tmp_path)
    assert preferences.permission_mode('alice') == 'risk'
    preferences.set_permission_mode('alice', 'request')
    assert StoragePreferences(preferences.index_path, program).permission_mode('alice') == 'request'
    assert preferences.permission_mode('bob') == 'risk'
    with pytest.raises(ValueError):
        preferences.set_permission_mode('alice', 'unlimited')
    assert preferences.permission_mode('alice') == 'request'


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
    with pytest.raises(OSError):
        preferences.select('alice', program / 'missing')
    assert preferences.load('alice') is None


def test_window_uses_installation_data_without_folder_prompt(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QApplication

    from asset_based_agent.technical_platform import app as platform
    from asset_based_agent.technical_platform.store import PlatformStore
    qt = QApplication.instance() or QApplication([])
    assert qt
    preferences, program, _ = make_preferences(tmp_path)
    calls = []
    monkeypatch.setattr(platform.QFileDialog, 'getExistingDirectory',
                        lambda *a: calls.append('prompt') or '')
    window = platform.PlatformWindow(PlatformStore(tmp_path / 'project.sqlite', 'alice'),
                                     storage_preferences=preferences)
    try:
        assert window.permission_button.text() == '帮我批准'
        window.set_agent_permission_mode('full')
        assert window.permission_button.text() == '范围内自动执行'
        assert preferences.permission_mode('alice') == 'full'
        assert calls == []
        assert window.ensure_storage_layout().data_root == (program / 'data').resolve()
        assert window.ensure_storage_layout().data_root == (program / 'data').resolve()
        assert calls == []
        (program / 'data').rename(tmp_path / 'removed-data')
        assert window.ensure_storage_layout() is None
        assert calls == []
        assert '不可用' in window.status.text()
    finally:
        window.close()
