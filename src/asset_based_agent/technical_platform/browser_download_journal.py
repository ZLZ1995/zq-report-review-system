"""Registered download staging only; never scan user folders for cleanup."""
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from .browser_downloads import DownloadTarget, validate_filename
from .project_catalog import validate_business_directory


class DownloadJournal:
    def __init__(self, path: Path):
        self.path = path

    @contextmanager
    def _database(self):
        validate_business_directory(self.path.parent)
        for path in (self.path, Path(str(self.path)+'-journal'), Path(str(self.path)+'-wal'),
                     Path(str(self.path)+'-shm')):
            if path.resolve() != path or path.is_symlink():
                raise ValueError('Download journal path redirected')
            if path.exists() and (not path.is_file() or path.stat().st_nlink != 1):
                raise ValueError('Download journal is linked or not a file')
        db = sqlite3.connect(self.path, timeout=0)
        try:
            with db:
                version = db.execute('PRAGMA user_version').fetchone()[0]
                if version not in (0, 1):
                    raise ValueError('Unsupported download journal schema')
                db.execute('CREATE TABLE IF NOT EXISTS stages '
                           '(stage TEXT PRIMARY KEY, destination TEXT NOT NULL, device TEXT NOT NULL, inode TEXT NOT NULL)')
                db.execute('PRAGMA user_version=1')
                yield db
        finally:
            db.close()

    def track(self, target: DownloadTarget) -> None:
        target._validate_stage()
        stat = target.stage.stat()
        with self._database() as db:
            db.execute('INSERT INTO stages VALUES(?,?,?,?)',
                       (str(target.stage), str(target.destination), str(stat.st_dev), str(stat.st_ino)))

    def forget(self, stage: Path) -> None:
        with self._database() as db:
            db.execute('DELETE FROM stages WHERE stage=?', (str(stage),))

    def recover(self) -> tuple[int, int]:
        """Only called under a newly acquired profile lock, before Qt startup.

        Never run on profile reuse or after cancelling a live Chromium request.
        Unknown/replaced contents are retained for inspection, not recursively
        deleted. The final destination is never opened or removed.
        """
        removed, pending = 0, 0
        with self._database() as db:
            rows = db.execute('SELECT stage,destination,device,inode FROM stages').fetchall()
            for raw, destination, device, inode in rows:
                try:
                    stage, final = Path(raw), Path(destination)
                    if (not stage.is_absolute() or stage.resolve() != stage or stage.is_symlink()
                            or not stage.name.startswith('.zq-download-')
                            or stage.parent != final.parent or final.resolve() != final):
                        raise ValueError('Invalid registered stage')
                    validate_business_directory(stage.parent)
                    validate_filename(final.name)
                    if stage.exists():
                        stat = stage.stat()
                        if not stage.is_dir() or (str(stat.st_dev), str(stat.st_ino)) != (device, inode):
                            raise ValueError('Registered stage was replaced')
                        entries = list(stage.iterdir())
                        for entry in entries:
                            if (entry.name not in {'payload.part', 'payload.part.crdownload'}
                                    or entry.resolve() != entry or entry.is_symlink()
                                    or not entry.is_file()):
                                raise ValueError('Unrecognized staging content')
                        for entry in entries:
                            entry.unlink()
                        stage.rmdir()
                    db.execute('DELETE FROM stages WHERE stage=?', (raw,))
                    removed += 1
                except (ValueError, OSError):
                    pending += 1
        return removed, pending
