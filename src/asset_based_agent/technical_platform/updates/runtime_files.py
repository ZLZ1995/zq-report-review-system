"""Select the signed transition-only Qt helper before desktop startup.

The 0.2.7 updater rejects packages containing more than one ``.exe`` file.
The release archive therefore carries the fixed Qt helper as ``.pending`` and
points Qt at that exact executable path without renaming it.  Keeping the file
name stable also lets legacy launchers continue to identify one main EXE.
"""

import os
from collections.abc import MutableMapping
from pathlib import Path


def configure_webengine_helper(
    application_root: Path,
    *,
    environment: MutableMapping[str, str] | None = None,
) -> Path:
    root = application_root.resolve()
    if root != application_root or not root.is_dir():
        raise ValueError('Invalid application root')
    helper = root / '_internal' / 'PySide6' / 'QtWebEngineProcess.exe'
    pending = helper.with_suffix('.pending')
    if any(path.resolve() != path or path.is_symlink() for path in (helper, pending)):
        raise ValueError('WebEngine helper path is unsafe')
    if helper.is_file() and not pending.exists():
        selected = helper
    elif pending.is_file() and not helper.exists():
        selected = pending
    else:
        if helper.exists() or pending.exists():
            raise ValueError('WebEngine helper state is ambiguous')
        raise FileNotFoundError('WebEngine helper is missing')
    selected_environment = os.environ if environment is None else environment
    selected_environment['QTWEBENGINEPROCESS_PATH'] = str(selected)
    return selected
