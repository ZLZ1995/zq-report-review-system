import pytest


def test_three_permission_modes_expose_codex_style_labels_and_risk_policy():
    from asset_based_agent.technical_platform.agent_permission_modes import (
        permission_mode_options,
        requires_browser_confirmation,
        requires_confirmation,
    )

    assert [(item.id, item.title) for item in permission_mode_options()] == [
        ('request', '请求批准'),
        ('risk', '帮我批准'),
        ('full', '完全访问权限'),
    ]
    assert all(requires_browser_confirmation('request', action) for action in (
        'navigate', 'scroll', 'click', 'fill', 'select', 'download', 'upload'))
    assert not requires_browser_confirmation('risk', 'navigate')
    assert not requires_browser_confirmation('risk', 'scroll')
    assert all(requires_browser_confirmation('risk', action) for action in (
        'click', 'fill', 'select', 'download', 'upload'))
    assert not any(requires_browser_confirmation('full', action) for action in (
        'navigate', 'scroll', 'click', 'fill', 'select', 'download', 'upload'))
    assert requires_confirmation('request', 'network')
    assert requires_confirmation('request', 'generate_file')
    assert not requires_confirmation('risk', 'network')
    assert not requires_confirmation('risk', 'generate_file')
    assert requires_confirmation('risk', 'install_skill')
    assert requires_confirmation('risk', 'modify_file')
    assert not requires_confirmation('full', 'install_skill')
    assert not requires_confirmation('full', 'modify_file')


@pytest.mark.parametrize('mode', ['', 'automatic', 'FULL', None])
def test_permission_policy_rejects_unknown_modes(mode):
    from asset_based_agent.technical_platform.agent_permission_modes import (
        requires_browser_confirmation,
    )

    with pytest.raises(ValueError):
        requires_browser_confirmation(mode, 'navigate')


def test_request_mode_blocks_remote_understanding_before_any_model_call(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QApplication, QMessageBox

    from asset_based_agent.technical_platform.app import PlatformWindow
    from asset_based_agent.technical_platform.storage_preferences import (
        StoragePreferences,
    )
    from asset_based_agent.technical_platform.store import PlatformStore

    app = QApplication.instance() or QApplication([])
    assert app
    program = tmp_path / 'program'
    program.mkdir()
    preferences = StoragePreferences(tmp_path / 'settings.sqlite', program)
    store = PlatformStore(tmp_path / 'project.sqlite', 'alice')
    project = store.create_project('Permission')
    session = store.create_session(project)
    calls = []

    class Client:
        def understand_task(self, *_args, **_kwargs):
            calls.append('model')
            raise AssertionError('declined request reached the model')

    window = PlatformWindow(
        store, client=Client(), models=[{'model_id': 'm', 'display_name': 'Model'}],
        storage_preferences=preferences,
    )
    try:
        window.reload_projects(project)
        window.set_agent_permission_mode('request')
        monkeypatch.setattr(QMessageBox, 'question',
                            lambda *_args, **_kwargs: QMessageBox.StandardButton.No)
        window.composer.setPlainText('Use the model')
        window.submit()
        assert calls == []
        assert window.composer.toPlainText() == 'Use the model'
        assert store.messages(session) == []
    finally:
        window.close()
