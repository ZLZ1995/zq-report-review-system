"""Account-specific location hints only; no business content or secrets in index."""
import sqlite3
from contextlib import closing, contextmanager
from pathlib import Path

from .storage_layout import StorageLayout


class StoragePreferences:
    def __init__(self, index_path: Path, program_root: Path):
        self.index_path = index_path
        self.program_root = program_root
        index_path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(index_path)) as db, db:
            db.execute('CREATE TABLE IF NOT EXISTS storage_roots(owner TEXT PRIMARY KEY, root TEXT NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS account_settings('
                       'owner TEXT NOT NULL, name TEXT NOT NULL, value TEXT NOT NULL, '
                       'PRIMARY KEY(owner,name))')

    def permission_mode(self, owner: str) -> str:
        from .agent_permission_modes import validate_permission_mode

        with closing(sqlite3.connect(self.index_path.resolve().as_uri() + '?mode=rw', uri=True)) as db:
            row = db.execute("SELECT value FROM account_settings WHERE owner=? AND name='permission_mode'",
                             (owner,)).fetchone()
        return validate_permission_mode(row[0]) if row else 'risk'

    def set_permission_mode(self, owner: str, mode: str) -> None:
        from .agent_permission_modes import validate_permission_mode

        mode = validate_permission_mode(mode)
        with closing(sqlite3.connect(self.index_path.resolve().as_uri() + '?mode=rw', uri=True)) as db, db:
            db.execute("INSERT INTO account_settings(owner,name,value) VALUES(?,'permission_mode',?) "
                       'ON CONFLICT(owner,name) DO UPDATE SET value=excluded.value', (owner, mode))

    def load(self, owner: str) -> StorageLayout | None:
        with closing(sqlite3.connect(self.index_path.resolve().as_uri() + '?mode=rw', uri=True)) as db:
            row = db.execute('SELECT root FROM storage_roots WHERE owner=?', (owner,)).fetchone()
        return StorageLayout(self.program_root, Path(row[0]), owner) if row else None

    def ensure_default(self, owner: str) -> StorageLayout:
        """Create the fixed installation-local platform data root once.

        This directory contains browser/cache/update state only. Business
        projects remain in the explicit non-system-drive project locations.
        """
        current = self.load(owner)
        if current is not None:
            return current
        root = (self.program_root / 'data').resolve()
        try:
            root.mkdir(parents=True, exist_ok=True)
            probe = root / '.write-test'
            probe.write_bytes(b'zq')
            probe.unlink()
        except OSError as exc:
            raise OSError('软件安装目录不可写，无法建立平台数据目录。') from exc
        return self.select(owner, root)

    @contextmanager
    def use(self, owner: str):
        """Hold a shared SQLite lock for the entire consumer lifetime.

        Consumers must close profile/files BEFORE exiting this context. This
        index deliberately uses rollback journaling; WAL readers would not
        exclude a migration writer. Multiple readers may coexist.
        """
        with closing(sqlite3.connect(
            self.index_path.resolve().as_uri() + '?mode=rw', uri=True, timeout=0,
        )) as db:
            if db.execute('PRAGMA journal_mode').fetchone()[0].lower() != 'delete':
                raise ValueError('Storage lease index requires DELETE journaling')
            db.execute('BEGIN')
            try:
                row = db.execute('SELECT root FROM storage_roots WHERE owner=?', (owner,)).fetchone()
                if not row:
                    raise ValueError('尚未设置平台数据目录。')
                yield StorageLayout(self.program_root, Path(row[0]), owner)
            finally:
                db.rollback()

    def select(self, owner: str, root: Path) -> StorageLayout:
        layout = StorageLayout(self.program_root, root, owner)
        with closing(sqlite3.connect(self.index_path.resolve().as_uri() + '?mode=rw', uri=True)) as db, db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT root FROM storage_roots WHERE owner=?', (owner,)).fetchone()
            if row and Path(row[0]) != layout.data_root:
                raise ValueError('已有数据目录不能直接替换；需要完成数据迁移后再切换。')
            db.execute('INSERT OR IGNORE INTO storage_roots VALUES(?,?)', (owner, str(layout.data_root)))
        return layout

    def migrate(self, owner: str, root: Path, *, confirmed: bool, consumers_closed: bool) -> StorageLayout:
        from .storage_migration import copy_account_tree
        if confirmed is not True or consumers_closed is not True:
            raise PermissionError('迁移需要明确确认并关闭所有数据使用者。')
        old = self.load(owner)
        if old is None:
            raise ValueError('尚未设置源目录。')
        new = StorageLayout(self.program_root, root, owner)
        # Exclude live use() consumers and preference writers until verification
        # and commit. A boolean closed claim alone is not a storage lock.
        with closing(sqlite3.connect(self.index_path.resolve().as_uri() + '?mode=rw', uri=True, timeout=0)) as db, db:
            if db.execute('PRAGMA journal_mode').fetchone()[0].lower() != 'delete':
                raise ValueError('Storage lease index requires DELETE journaling')
            db.execute('BEGIN EXCLUSIVE')
            row = db.execute('SELECT root FROM storage_roots WHERE owner=?', (owner,)).fetchone()
            if not row or row[0] != str(old.data_root):
                raise ValueError('源目录设置已变化。')
            copy_account_tree(old.cache.parent, new.cache.parent)
            db.execute('UPDATE storage_roots SET root=? WHERE owner=?', (str(new.data_root), owner))
        return new
