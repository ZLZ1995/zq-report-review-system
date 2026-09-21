"""Consistent SQLite snapshots and verified recovery copies, never in-place restore."""

import hashlib
import os
import shutil
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from ..project_catalog import validate_business_directory


@dataclass(frozen=True)
class DatabaseBackup:
    path: Path
    sha256: str
    size: int


def _digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open('rb') as source:
        while chunk := source.read(1024 * 1024):
            value.update(chunk)
    return value.hexdigest()


def _plain_path(path: Path) -> None:
    if not path.is_absolute() or path.resolve() != path:
        raise ValueError('Explicit non-redirected path required')


def backup_database(source: Path, folder: Path) -> DatabaseBackup:
    _plain_path(source)
    _plain_path(folder)
    validate_business_directory(folder)
    if not source.is_file():
        raise FileNotFoundError('Database source missing')
    target = folder / f'database-{uuid4().hex}.sqlite'
    try:
        with closing(sqlite3.connect(source.as_uri() + '?mode=ro', uri=True, timeout=5)) as db:
            if db.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
                raise ValueError('Source database failed integrity check')
            estimated = db.execute('PRAGMA page_count').fetchone()[0] * db.execute('PRAGMA page_size').fetchone()[0]
            if shutil.disk_usage(folder).free < estimated + 32 * 1024**2:
                raise OSError('Insufficient backup space')
            with target.open('xb'):
                pass
            with closing(sqlite3.connect(target)) as backup:
                db.backup(backup)
                if backup.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
                    raise ValueError('Backup integrity check failed')
                backup.execute('PRAGMA journal_mode=DELETE')
    except sqlite3.DatabaseError:
        raise ValueError('Database snapshot failed') from None
    with target.open('r+b') as stream:
        os.fsync(stream.fileno())
    return DatabaseBackup(target, _digest(target), target.stat().st_size)


def restore_database_copy(snapshot: DatabaseBackup, destination: Path) -> Path:
    """Materialize verified recovery candidate; activation is a separate locked step."""
    _plain_path(snapshot.path)
    _plain_path(destination)
    validate_business_directory(destination.parent)
    if destination.exists():
        raise FileExistsError('Recovery never overwrites existing data')
    if snapshot.path.stat().st_size != snapshot.size or _digest(snapshot.path) != snapshot.sha256:
        raise ValueError('Backup was modified; refusing recovery')
    with (
        closing(sqlite3.connect(snapshot.path.as_uri() + '?mode=ro', uri=True)) as db,
    ):
        if db.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
            raise ValueError('Backup database failed integrity check')
    with snapshot.path.open('rb') as source, destination.open('xb') as output:
        shutil.copyfileobj(source, output, 1024 * 1024)
        output.flush()
        os.fsync(output.fileno())
    if _digest(destination) != snapshot.sha256:
        raise ValueError('Recovery copy changed during materialization')
    return destination

