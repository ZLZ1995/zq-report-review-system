"""Copy and verify one inactive account tree; never move or delete its source."""
import hashlib
import shutil
import time
from pathlib import Path
from uuid import uuid4


def inventory(root: Path):
    if not root.is_dir() or root.resolve() != root:
        raise ValueError('Source storage is missing or redirected')
    result = {}
    for path in sorted(root.rglob('*')):
        if path.is_symlink() or path.resolve() != path:
            raise ValueError('Linked storage content cannot be migrated')
        relative = path.relative_to(root).as_posix()
        if path.is_dir():
            result[relative] = None
        elif path.is_file():
            digest = hashlib.sha256()
            with path.open('rb') as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b''):
                    digest.update(block)
            result[relative] = (path.stat().st_size, digest.hexdigest())
        else:
            raise ValueError('Unsupported storage entry')
    return result


def copy_account_tree(source: Path, destination: Path):
    if source == destination or destination.exists():
        raise ValueError('Target account directory already exists')
    if source.is_relative_to(destination) or destination.is_relative_to(source):
        raise ValueError('Migration directories must be disjoint')
    before = inventory(source)
    destination.parent.mkdir(parents=True, exist_ok=True)
    stage = destination.parent / f'migration-{uuid4().hex}'
    stage.mkdir(exist_ok=False)
    # Failed staging directories are retained, never activated or silently removed.
    for relative, metadata in before.items():
        target = stage / relative
        if metadata is None:
            target.mkdir(parents=True, exist_ok=True)
        else:
            original = source / relative
            if original.resolve() != original or original.is_symlink():
                raise ValueError('Source redirected during migration')
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(original, target)
    if inventory(stage) != before or inventory(source) != before:
        raise ValueError('Migration validation failed or source changed')
    for attempt in range(4):
        if destination.exists() or destination.resolve() != destination:
            raise ValueError('Migration destination changed')
        if attempt and (inventory(stage) != before or inventory(source) != before):
            raise ValueError('Migration content changed while waiting for rename')
        try:
            stage.rename(destination)
            return
        except PermissionError as exc:
            if getattr(exc, 'winerror', None) not in {5, 32, 33} or attempt == 3:
                raise
            time.sleep((0.02, 0.05, 0.1)[attempt])
