"""Restore a signed transition-only Qt helper before desktop startup.

The 0.2.7 updater rejects packages containing more than one ``.exe`` file.
The release archive therefore carries the fixed Qt helper as ``.pending``;
the new client restores it locally before importing any WebEngine UI.
"""

import os
from pathlib import Path


def restore_webengine_helper(application_root: Path) -> Path:
    root = application_root.resolve()
    if root != application_root or not root.is_dir():
        raise ValueError('Invalid application root')
    helper = root / '_internal' / 'PySide6' / 'QtWebEngineProcess.exe'
    pending = helper.with_suffix('.pending')
    if any(path.resolve() != path or path.is_symlink() for path in (helper, pending)):
        raise ValueError('WebEngine helper path is unsafe')
    if helper.is_file() and not pending.exists():
        return helper
    if pending.is_file() and not helper.exists():
        os.replace(pending, helper)
        if not helper.is_file():
            raise OSError('WebEngine helper restoration failed')
        return helper
    if helper.exists() or pending.exists():
        raise ValueError('WebEngine helper state is ambiguous')
    raise FileNotFoundError('WebEngine helper is missing')
