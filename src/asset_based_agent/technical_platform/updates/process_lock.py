"""Shared runtime / exclusive installer locks using OS-backed SQLite locking.

This control file belongs to an installation, NOT an account/project. Every
launcher and updater must use the same explicit path. Process exit releases
locks; there is no guessed stale PID deletion or forced process termination.
"""

import sqlite3
from collections.abc import Iterator
from contextlib import closing, contextmanager
from pathlib import Path

from ..project_catalog import validate_business_directory


class InstallationLock:
    def __init__(self, path: Path):
        self.path = path

    @staticmethod
    def _validate(path: Path) -> None:
        if not path.is_absolute() or path.resolve() != path:
            raise ValueError('Installation lock requires an absolute non-redirected path')
        validate_business_directory(path.parent)

    @classmethod
    def initialize(cls, path: Path) -> None:
        """Only initial install creates this file; normal startup never recreates it."""
        cls._validate(path)
        with path.open('xb'):
            pass
        with closing(sqlite3.connect(path.as_uri() + '?mode=rw', uri=True)) as db, db:
            db.execute('PRAGMA journal_mode=DELETE')
            db.execute('CREATE TABLE installation_control (format TEXT NOT NULL)')
            db.execute("INSERT INTO installation_control VALUES ('zq-install-lock-v1')")
            db.execute('PRAGMA user_version=1')

    @contextmanager
    def _lease(self, *, exclusive: bool) -> Iterator[None]:
        self._validate(self.path)
        if not self.path.is_file():
            raise FileNotFoundError('Installation lock missing; repair installation explicitly')
        db = sqlite3.connect(self.path.as_uri() + '?mode=rw', uri=True, timeout=0)
        try:
            if db.execute('PRAGMA journal_mode').fetchone()[0].lower() != 'delete':
                raise ValueError('Installation lock requires DELETE journal mode')
            db.execute('BEGIN EXCLUSIVE' if exclusive else 'BEGIN')
            if (db.execute('PRAGMA user_version').fetchone()[0] != 1 or
                    db.execute('SELECT format FROM installation_control').fetchall() != [('zq-install-lock-v1',)]):
                raise ValueError('Invalid installation control format')
        except sqlite3.DatabaseError as exc:
            db.close()
            if 'locked' in str(exc).lower() or 'busy' in str(exc).lower():
                raise BlockingIOError('Another runtime or installer holds the installation lock') from None
            raise ValueError('Invalid installation control database') from None
        except BaseException:
            db.close()
            raise
        try:
            yield
        finally:
            db.rollback()
            db.close()

    def runtime(self):
        return self._lease(exclusive=False)

    def installation(self):
        return self._lease(exclusive=True)

