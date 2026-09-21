import time

import pytest
from PySide6.QtWidgets import QApplication, QMessageBox

from asset_based_agent.technical_platform.storage_preferences import StoragePreferences


@pytest.fixture(scope='module')
def qt():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def storage(tmp_path, qt):
    program, old_root, target = [tmp_path / name for name in ('program', 'old', 'new')]
    for folder in (program, old_root, target):
        folder.mkdir()
    preferences = StoragePreferences(tmp_path / 'index.sqlite', program)
    old = preferences.select('alice', old_root)
    old.prepare()
    (old.downloads / 'synthetic.txt').write_text('synthetic only', encoding='utf-8')
    return qt, preferences, old, target


def finish(qt, dialog):
    deadline = time.monotonic() + 10
    while dialog.worker is not None and time.monotonic() < deadline:
        qt.processEvents()
        time.sleep(0.01)
    assert dialog.worker is None


def test_confirmed_migration_switches_only_after_verified_copy(storage, monkeypatch):
    from asset_based_agent.technical_platform import storage_dialog as ui
    qt, preferences, old, target = storage
    monkeypatch.setattr(ui.QFileDialog, 'getExistingDirectory', lambda *a: str(target))
    monkeypatch.setattr(ui.QMessageBox, 'question', lambda *a: QMessageBox.StandardButton.Yes)
    dialog = ui.StorageDialog(preferences, 'alice')
    try:
        dialog.migrate()
        assert dialog.worker is not None
        assert not dialog.migrate_button.isEnabled()
        finish(qt, dialog)
        assert preferences.load('alice').data_root == target
        assert '已完成' in dialog.status.text()
        assert '原目录保留' in dialog.status.text()
        assert (old.downloads / 'synthetic.txt').read_text(encoding='utf-8') == 'synthetic only'
    finally:
        if dialog.worker:
            dialog.worker.wait()
            qt.processEvents()
        dialog.close()


def test_refused_migration_does_not_write_target(storage, monkeypatch):
    from asset_based_agent.technical_platform import storage_dialog as ui
    _, preferences, old, target = storage
    monkeypatch.setattr(ui.QFileDialog, 'getExistingDirectory', lambda *a: str(target))
    monkeypatch.setattr(ui.QMessageBox, 'question', lambda *a: QMessageBox.StandardButton.No)
    dialog = ui.StorageDialog(preferences, 'alice')
    dialog.migrate()
    assert dialog.worker is None
    assert preferences.load('alice').data_root == old.data_root
    assert not list(target.iterdir())
    dialog.close()


def test_busy_storage_reports_failure_and_keeps_original(storage, monkeypatch):
    from asset_based_agent.technical_platform import storage_dialog as ui
    qt, preferences, old, target = storage
    monkeypatch.setattr(ui.QFileDialog, 'getExistingDirectory', lambda *a: str(target))
    monkeypatch.setattr(ui.QMessageBox, 'question', lambda *a: QMessageBox.StandardButton.Yes)
    dialog = ui.StorageDialog(preferences, 'alice')
    with preferences.use('alice'):
        dialog.migrate()
        finish(qt, dialog)
    assert '未切换' in dialog.status.text()
    assert preferences.load('alice').data_root == old.data_root
    assert not list(target.iterdir())
    dialog.close()


def test_window_blocks_settings_during_task(storage, tmp_path):
    from threading import Event
    from types import SimpleNamespace

    from asset_based_agent.technical_platform.app import PlatformWindow
    from asset_based_agent.technical_platform.store import PlatformStore
    from asset_based_agent.technical_platform.task_manager import TaskBinding
    _, preferences, _, _ = storage
    window = PlatformWindow(PlatformStore(tmp_path / 'project.sqlite', 'alice'),
                            storage_preferences=preferences)
    binding = TaskBinding('alice', 'background-project', 'background-session', 'task')
    worker = SimpleNamespace(cancel=Event(), isRunning=lambda: False)
    window.task_manager.register(binding, worker)
    try:
        window.configure_storage()
        assert '任务' in window.status.text() and '结束' in window.status.text()
    finally:
        window.task_manager.finish(binding, worker)
        window.close()


def test_repeated_failures_release_threads_and_keep_dialog_alive(storage, monkeypatch):
    import threading

    from asset_based_agent.technical_platform import storage_dialog as ui
    qt, preferences, old, target = storage
    release = threading.Event()
    entered = threading.Event()

    def fail(*args, **kwargs):
        entered.set()
        assert release.wait(5)
        raise OSError('synthetic failure with private details')

    monkeypatch.setattr(preferences, 'migrate', fail)
    monkeypatch.setattr(ui.QFileDialog, 'getExistingDirectory', lambda *a: str(target))
    monkeypatch.setattr(ui.QMessageBox, 'question', lambda *a: QMessageBox.StandardButton.Yes)
    for _ in range(5):
        release.clear()
        entered.clear()
        dialog = ui.StorageDialog(preferences, 'alice')
        dialog.show()
        dialog.migrate()
        try:
            assert entered.wait(5)
            dialog.reject()
            dialog.close()
            assert dialog.isVisible()
        finally:
            release.set()
            finish(qt, dialog)
        assert 'private details' not in dialog.status.text()
        assert preferences.load('alice').data_root == old.data_root
        dialog.close()
        assert not dialog.isVisible()
        dialog.deleteLater()
        qt.processEvents()


def test_window_opens_migration_dialog_for_current_account(storage, tmp_path, monkeypatch):
    from asset_based_agent.technical_platform import storage_dialog as ui
    from asset_based_agent.technical_platform.app import PlatformWindow
    from asset_based_agent.technical_platform.store import PlatformStore
    _, preferences, _, _ = storage
    opened = []
    monkeypatch.setattr(ui.StorageDialog, 'exec', lambda self: opened.append(self.owner))
    window = PlatformWindow(PlatformStore(tmp_path / 'project.sqlite', 'alice'),
                            storage_preferences=preferences)
    try:
        window.configure_storage()
        assert opened == ['alice']
    finally:
        window.close()
