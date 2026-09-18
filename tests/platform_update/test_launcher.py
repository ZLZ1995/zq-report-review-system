import json

import pytest

from asset_based_agent.technical_platform.updates.journal import UpdateJournal
from asset_based_agent.technical_platform.updates.launcher import launch_selected
from asset_based_agent.technical_platform.updates.manifest import UpdatePolicy
from asset_based_agent.technical_platform.updates.process_lock import InstallationLock


def test_launcher_holds_shared_installation_lock_for_entire_child_lifetime(tmp_path):
    policy = UpdatePolicy('0.2.6', 9, 'windows', 'x86_64', 1, 10, '1.0.0', frozenset({'test.test'}))
    UpdateJournal.initialize(tmp_path / 'update-state.sqlite', policy)
    InstallationLock.initialize(tmp_path / 'installation-lock.sqlite')
    metadata = dict(vars(policy))
    metadata['allowed_hosts'] = list(policy.allowed_hosts)
    (tmp_path / 'installation-policy.json').write_text(json.dumps(metadata), encoding='utf8')
    executable = tmp_path / 'versions/0.2.6/ZQ\u6280\u672f\u5e73\u53f0/ZQ\u6280\u672f\u5e73\u53f0.exe'
    executable.parent.mkdir(parents=True)
    executable.write_bytes(b'synthetic')
    helper = executable.parent / '_internal/PySide6/QtWebEngineProcess.exe'
    helper.parent.mkdir(parents=True)
    helper.write_bytes(b'helper')
    calls = []
    def run(command, **kwargs):
        calls.append(command)
        with pytest.raises(BlockingIOError), InstallationLock(tmp_path / 'installation-lock.sqlite').installation():
            pytest.fail('installer entered while child is active')
        from types import SimpleNamespace
        return SimpleNamespace(returncode=0)
    assert launch_selected(tmp_path, runner=run) == 0
    assert calls == [[str(executable)]]
    with InstallationLock(tmp_path / 'installation-lock.sqlite').installation():
        pass


def test_launcher_never_creates_missing_installation(tmp_path):
    with pytest.raises(FileNotFoundError):
        launch_selected(tmp_path, runner=lambda *_: pytest.fail('must not launch'))
    assert list(tmp_path.iterdir()) == []


def test_direct_active_managed_exe_is_not_rejected_by_damaged_path_encoding(tmp_path, monkeypatch):
    import sys

    from asset_based_agent.technical_platform.updates.launcher import run_managed

    policy = UpdatePolicy('0.2.8', 11, 'windows', 'x86_64', 1, 10, '1.0.0', frozenset({'test.test'}))
    UpdateJournal.initialize(tmp_path / 'update-state.sqlite', policy)
    InstallationLock.initialize(tmp_path / 'installation-lock.sqlite')
    values = {**vars(policy), 'allowed_hosts': list(policy.allowed_hosts)}
    (tmp_path / 'installation-policy.json').write_text(json.dumps(values), encoding='utf8')
    monkeypatch.setattr(sys, 'frozen', True, raising=False)
    executable = tmp_path / 'versions/0.2.8/ZQ\u6280\u672f\u5e73\u53f0/ZQ\u6280\u672f\u5e73\u53f0.exe'
    executable.parent.mkdir(parents=True)
    executable.write_bytes(b'active')
    monkeypatch.setattr(sys, 'executable', str(executable))
    monkeypatch.setenv('ZQ_INSTALLATION_ROOT', str(tmp_path))
    assert run_managed(lambda: 17) == 17


def test_direct_old_managed_exe_redirects_to_stable_launcher(tmp_path, monkeypatch):
    import sys

    from asset_based_agent.technical_platform.updates.launcher import run_managed

    policy = UpdatePolicy('0.2.8', 11, 'windows', 'x86_64', 1, 10, '1.0.0', frozenset({'test.test'}))
    UpdateJournal.initialize(tmp_path / 'update-state.sqlite', policy)
    InstallationLock.initialize(tmp_path / 'installation-lock.sqlite')
    values = {**vars(policy), 'allowed_hosts': list(policy.allowed_hosts)}
    (tmp_path / 'installation-policy.json').write_text(json.dumps(values), encoding='utf8')
    launcher = tmp_path / 'ZQ\u6280\u672f\u5e73\u53f0\u542f\u52a8\u5668.exe'
    launcher.write_bytes(b'launcher')
    active = tmp_path / 'versions/0.2.8/ZQ\u6280\u672f\u5e73\u53f0/ZQ\u6280\u672f\u5e73\u53f0.exe'
    active.parent.mkdir(parents=True)
    active.write_bytes(b'active')
    monkeypatch.setattr(sys, 'frozen', True, raising=False)
    monkeypatch.setattr(sys, 'executable', str(
        tmp_path / 'versions/0.2.7/ZQ\u6280\u672f\u5e73\u53f0/ZQ\u6280\u672f\u5e73\u53f0.exe'))
    monkeypatch.setenv('ZQ_INSTALLATION_ROOT', str(tmp_path))
    calls = []

    class Process:
        pass

    monkeypatch.setattr('asset_based_agent.technical_platform.updates.launcher.subprocess.Popen',
                        lambda command, **kwargs: calls.append((command, kwargs)) or Process())
    assert run_managed(lambda: pytest.fail('obsolete client started')) == 0
    assert calls[0][0] == [str(launcher)]
