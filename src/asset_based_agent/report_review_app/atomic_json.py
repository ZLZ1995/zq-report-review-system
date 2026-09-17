"""Atomic JSON replacement with bounded Windows contention recovery."""
import json
import os
import tempfile
import time
from pathlib import Path


def write_json_atomic(path: Path, payload: dict[str, object]) -> None:
    # Serialize before creating a file; an invalid payload cannot alter old data.
    content = json.dumps(payload, ensure_ascii=False, indent=2)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode='w', encoding='utf-8', dir=path.parent,
            prefix='.zq-', suffix='.tmp', delete=False,
        ) as stream:
            temporary = Path(stream.name)
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        for attempt in range(4):
            try:
                os.replace(temporary, path)
                return
            except PermissionError as exc:
                if getattr(exc, 'winerror', None) not in {5, 32, 33} or attempt == 3:
                    raise
                time.sleep((0.02, 0.05, 0.1)[attempt])
    finally:
        # Only this call's exclusive temporary file is eligible for cleanup.
        # Cleanup failure must not obscure a replacement failure.
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
