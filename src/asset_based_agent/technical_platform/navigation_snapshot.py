"""Read-only, zero busy-wait navigation queries; never migrate/open a workspace."""
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from .local_migrations import SCHEMA_VERSION
from .project_catalog import ProjectCatalog, validate_business_directory


@contextmanager
def _read(path):
    db = sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True, timeout=0)
    try:
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA query_only=ON')
        db.execute('BEGIN')
        yield db
    finally:
        db.close()


def _projects(db, owner):
    if db.execute('PRAGMA user_version').fetchone()[0] != SCHEMA_VERSION:
        raise ValueError('Open this project explicitly to check its schema')
    projects = {row['id']: {**dict(row), 'sessions': []} for row in db.execute(
        'SELECT id,name,archived FROM projects WHERE owner=? ORDER BY created,id', (owner,))}
    # Aggregate once per database, not a full message scan for every session.
    counts = dict(db.execute('''
        SELECT x.session,COUNT(*) FROM messages x
        JOIN sessions s ON s.id=x.session JOIN projects p ON p.id=s.project
        LEFT JOIN session_metadata m ON m.session=s.id
        WHERE p.owner=? AND p.archived=0 AND COALESCE(m.archived,0)=0
        AND x.role='assistant' AND x.id>COALESCE(m.last_read_message,0)
        GROUP BY x.session''', (owner,)))
    rows = db.execute('''SELECT s.id,s.project,s.title,m.parent_session,m.fork_message
        FROM sessions s JOIN projects p ON p.id=s.project
        LEFT JOIN session_metadata m ON m.session=s.id
        WHERE p.owner=? AND p.archived=0 AND COALESCE(m.archived,0)=0
        ORDER BY s.created,s.id''', (owner,))
    for row in rows:
        projects[row['project']]['sessions'].append({**dict(row), 'unread_count': counts.get(row['id'], 0)})
    return projects


def navigation_snapshot(store):
    if not isinstance(store, ProjectCatalog):
        with _read(store.path) as db:
            return [p for p in _projects(db, store.owner).values() if not p['archived']]
    with _read(store.index_path) as db:
        locations = list(db.execute('SELECT * FROM locations WHERE owner=? ORDER BY rowid', (store.owner,)))
    projects = []
    databases = {}
    for location in locations:
        try:
            path = Path(location['path']).resolve()
            validate_business_directory(path.parent)
            if path not in databases:
                databases[path] = None
                with _read(path) as db:
                    databases[path] = _projects(db, store.owner)
            records = databases[path]
            if records is None or location['project'] not in records:
                raise ValueError('Project is unavailable or outside this account')
            project = records[location['project']]
            if not project['archived']:
                projects.append(project)
        except (OSError, ValueError, PermissionError, sqlite3.Error):
            projects.append({'id': location['project'], 'name': location['name'],
                             'unavailable': True, 'sessions': []})
    return projects
