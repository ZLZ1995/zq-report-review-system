"""Stable launcher and child-owned runtime leases for managed installations."""

import json
import os
import subprocess
import sys
from pathlib import Path

from .journal import UpdateJournal
from .manifest import UpdatePolicy
from .process_lock import InstallationLock

CLIENT_DIRECTORY = 'ZQ\u6280\u672f\u5e73\u53f0'
CLIENT_EXECUTABLE = CLIENT_DIRECTORY + '.exe'
INSTALLATION_LAUNCHER = CLIENT_DIRECTORY + '\u542f\u52a8\u5668.exe'


def _active_executable(root: Path, version: str) -> Path:
    version_root = root / 'versions' / version
    executable = version_root / CLIENT_DIRECTORY / CLIENT_EXECUTABLE
    if (not executable.is_file() or executable.resolve() != executable
            or not executable.is_relative_to(version_root)):
        raise FileNotFoundError('Active client executable missing')
    return executable


def load_policy(root: Path) -> UpdatePolicy:
    with (root / 'installation-policy.json').open('rb') as source:
        raw = source.read(65537)
    if len(raw) > 65536:
        raise ValueError('Installation policy exceeds limit')
    values = json.loads(raw)
    hosts = values.get('allowed_hosts')
    if not isinstance(hosts, list) or not hosts or any(not isinstance(h, str) for h in hosts):
        raise ValueError('Invalid installation download hosts')
    return UpdatePolicy(**{**values, 'allowed_hosts': frozenset(hosts)})


def launch_selected(root: Path, *, runner=subprocess.run) -> int:
    with InstallationLock(root / 'installation-lock.sqlite').runtime():
        journal = UpdateJournal(root / 'update-state.sqlite', load_policy(root))
        version = journal.launch_version()
        executable = _active_executable(root, version)
        environment = os.environ.copy()
        environment['ZQ_INSTALLATION_ROOT'] = str(root)
        result = runner([str(executable)], cwd=executable.parent, env=environment,
                        check=False, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        return result.returncode


def run_managed(callback) -> int:
    """Each actual client/worker owns a lease even if its launcher crashes."""
    configured = os.environ.get('ZQ_INSTALLATION_ROOT')
    if not configured and getattr(sys, 'frozen', False):
        executable = Path(sys.executable)
        if executable.parent.parent.parent.name == 'versions':
            configured = str(executable.parent.parent.parent.parent)
    if configured:
        root = Path(configured)
        with InstallationLock(root / 'installation-lock.sqlite').runtime():
            # Fail closed on incomplete activation, including direct EXE startup.
            version = UpdateJournal(root / 'update-state.sqlite', load_policy(root)).launch_version()
            if getattr(sys, 'frozen', False):
                expected = _active_executable(root, version)
                if Path(sys.executable).resolve() != expected.resolve():
                    launcher = root / INSTALLATION_LAUNCHER
                    if (not launcher.is_file() or launcher.resolve() != launcher
                            or launcher.parent != root):
                        raise FileNotFoundError('Installation launcher missing')
                    subprocess.Popen(
                        [str(launcher)], cwd=root, env=os.environ.copy(), close_fds=True,
                        creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
                    )
                    return 0
            return callback()
    return callback()  # Existing unmanaged/source launch remains compatible.
