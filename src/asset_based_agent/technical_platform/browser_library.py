"""User-managed browser bookmarks/home, local to an account and environment."""
import sqlite3
from contextlib import closing, contextmanager

from .browser_policy import navigation_url


class BrowserLibrary:
    def __init__(self, preferences, owner: str, *, environment: str = 'production'):
        if environment not in {'production', 'test'}:
            raise ValueError('Unknown browser environment')
        self.preferences, self.owner, self.environment = preferences, owner, environment

    @contextmanager
    def _connect(self):
        with self.preferences.use(self.owner) as layout:
            path = layout.browser_profiles / f'{self.environment}-library.sqlite'
            if path.resolve() != path:
                raise ValueError('Browser library path is redirected')
            path.parent.mkdir(parents=True, exist_ok=True)
            with closing(sqlite3.connect(path, timeout=0)) as db, db:
                version = db.execute('PRAGMA user_version').fetchone()[0]
                if version not in {0, 1}:
                    raise ValueError('Unsupported browser library version')
                db.execute('CREATE TABLE IF NOT EXISTS bookmarks(url TEXT PRIMARY KEY, title TEXT NOT NULL)')
                db.execute('CREATE TABLE IF NOT EXISTS settings(name TEXT PRIMARY KEY, value TEXT NOT NULL)')
                db.execute('PRAGMA user_version=1')
                yield db

    @staticmethod
    def _url(value: str) -> str:
        if len(value) > 4096:
            raise ValueError('Browser address is too long')
        return navigation_url(value).toString()

    def save(self, title: str, url: str) -> None:
        url = self._url(url)
        if not title.strip() or len(title) > 120 or any(ord(c) < 32 for c in title):
            raise ValueError('Invalid bookmark title')
        with self._connect() as db:
            db.execute('INSERT INTO bookmarks(url,title) VALUES(?,?) '
                       'ON CONFLICT(url) DO UPDATE SET title=excluded.title', (url, title.strip()))

    def bookmarks(self) -> list[tuple[str, str]]:
        with self._connect() as db:
            rows = db.execute('SELECT title,url FROM bookmarks ORDER BY title,url').fetchall()
        return [(title, self._url(url)) for title, url in rows]

    def remove(self, url: str) -> None:
        url = self._url(url)
        with self._connect() as db:
            db.execute('DELETE FROM bookmarks WHERE url=?', (url,))

    def home(self) -> str:
        with self._connect() as db:
            row = db.execute("SELECT value FROM settings WHERE name='home'").fetchone()
        return self._url(row[0]) if row else 'about:blank'

    def set_home(self, url: str) -> None:
        url = self._url(url)
        with self._connect() as db:
            db.execute("INSERT INTO settings(name,value) VALUES('home',?) "
                       'ON CONFLICT(name) DO UPDATE SET value=excluded.value', (url,))
