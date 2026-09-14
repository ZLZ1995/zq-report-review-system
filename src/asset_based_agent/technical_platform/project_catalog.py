"""Small per-account location index; all business state remains in project directories."""

import os
import sqlite3
from pathlib import Path

from .store import PlatformStore


def validate_business_directory(path: Path, *, system_drive=None):
    path = path.resolve()
    drive = system_drive or os.environ.get("SystemDrive", "C:")
    if path.drive.casefold() == drive.casefold():
        raise ValueError("业务项目不能保存在系统盘，请选择其他磁盘目录")
    if not path.is_dir():
        raise OSError("项目目录不存在，请重新定位；不会自动创建替代目录")
    return path


class ProjectCatalog:
    def __init__(self, index_path: Path, owner: str):
        self.index_path, self.owner = index_path, owner
        self.active = None
        index_path.parent.mkdir(parents=True, exist_ok=True)
        with self.index() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS locations(
                  owner TEXT, project TEXT, name TEXT, path TEXT, session TEXT,
                  PRIMARY KEY(owner,project));
                CREATE TABLE IF NOT EXISTS selection(owner TEXT PRIMARY KEY, project TEXT);
            """)

    def index(self):
        # SQLite context transactions do not close connections; use a scoped wrapper.
        from contextlib import contextmanager

        @contextmanager
        def connection():
            db = sqlite3.connect(self.index_path)
            db.row_factory = sqlite3.Row
            try:
                with db:
                    yield db
            finally:
                db.close()
        return connection()

    @property
    def last_project(self):
        with self.index() as db:
            row = db.execute("SELECT project FROM selection WHERE owner=?", (self.owner,)).fetchone()
        return row[0] if row else None

    @property
    def last_session(self):
        with self.index() as db:
            row = db.execute("SELECT session FROM locations WHERE owner=? AND project=?",
                             (self.owner, self.last_project)).fetchone()
        return row[0] if row else None

    def remember_session(self, session):
        self.active.session(session)
        with self.index() as db:
            db.execute("UPDATE locations SET session=? WHERE owner=? AND project=?",
                       (session, self.owner, self.last_project))

    def _register(self, store, project):
        with self.index() as db:
            db.execute("INSERT INTO locations VALUES(?,?,?,?,NULL) ON CONFLICT(owner,project) "
                       "DO UPDATE SET name=excluded.name,path=excluded.path",
                       (self.owner, project["id"], project["name"], str(store.path.resolve())))

    def create_project(self, name, directory):
        root = validate_business_directory(Path(directory))
        path = root / ".zq" / "platform.sqlite"
        if path.exists():
            raise ValueError("目录已有项目数据，请使用打开已有项目")
        # Validate resolved metadata directory as well (junction/symlink safety).
        if path.parent.resolve().drive.casefold() == os.environ.get("SystemDrive", "C:").casefold():
            raise ValueError("项目数据目录不能指向系统盘")
        store = PlatformStore(path, self.owner)
        identity = store.create_project(name)
        self._register(store, store.project(identity))
        self.select_project(identity)
        return identity

    def open_directory(self, directory):
        root = validate_business_directory(Path(directory))
        path = root / ".zq" / "platform.sqlite"
        if not path.is_file():
            path = root / "platform.sqlite"
        if not path.is_file():
            raise OSError("此目录没有已有项目数据库")
        validate_business_directory(path.resolve().parent)
        store = PlatformStore(path, self.owner, create=False)
        projects = store.projects() + store.archived_projects()
        for project in projects:
            self._register(store, project)
        return [project["id"] for project in projects]

    def projects(self, archived=False):
        with self.index() as db:
            rows = list(db.execute("SELECT * FROM locations WHERE owner=? ORDER BY rowid", (self.owner,)))
        results = []
        for row in rows:
            try:
                path = Path(row["path"])
                if not path.is_file():
                    raise OSError("目录不可用")
                validate_business_directory(path.resolve().parent)
                project = PlatformStore(path, self.owner, create=False).project(row["project"])
                if bool(project["archived"]) == archived:
                    results.append({**project, "unavailable": False})
            except (OSError, ValueError, PermissionError, sqlite3.Error):
                if not archived:
                    results.append({"id": row["project"], "name": row["name"], "unavailable": True})
        return results

    def archived_projects(self):
        return self.projects(archived=True)

    def select_project(self, identity):
        self.active = None
        with self.index() as db:
            row = db.execute("SELECT path FROM locations WHERE owner=? AND project=?",
                             (self.owner, identity)).fetchone()
        if row is None:
            raise PermissionError("项目未登记或无权访问")
        path = Path(row[0])
        if not path.is_file():
            raise OSError("目录不可用，请通过打开已有项目重新定位")
        validate_business_directory(path.resolve().parent)
        store = PlatformStore(path, self.owner, create=False)
        store.project(identity)
        self.active = store
        with self.index() as db:
            db.execute("INSERT INTO selection VALUES(?,?) ON CONFLICT(owner) DO UPDATE SET project=excluded.project",
                       (self.owner, identity))

    def restore(self, identity):
        self.select_project(identity)
        self.active.restore(identity)

    def __getattr__(self, name):
        if self.active is None:
            raise ValueError("请先创建或打开非系统盘项目")
        # Recheck before every delegated operation; never recreate a missing root.
        if not self.active.path.is_file():
            raise OSError("项目目录不可用，操作已停止")
        return getattr(self.active, name)
