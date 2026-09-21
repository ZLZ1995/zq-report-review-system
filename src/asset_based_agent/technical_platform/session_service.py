"""Account-scoped conversation metadata; forks never inherit execution authority."""
import json
from hashlib import sha256
from uuid import uuid4

from .store import now


class SessionService:
    def __init__(self, store):
        from .project_catalog import ProjectCatalog
        self.store = store.active if isinstance(store, ProjectCatalog) else store
        if self.store is None:
            raise ValueError('No project selected')

    def _session(self, db, identity):
        row = db.execute('SELECT s.* FROM sessions s JOIN projects p ON p.id=s.project '
                         'WHERE s.id=? AND p.owner=?', (identity, self.store.owner)).fetchone()
        if row is None:
            raise PermissionError('Session is not owned by this account')
        return row

    @staticmethod
    def _title(title):
        if (not isinstance(title, str) or not 1 <= len(title.strip()) <= 100
                or any(ord(char) < 32 for char in title)):
            raise ValueError('Conversation title must contain 1 to 100 printable characters')
        return title.strip()

    @staticmethod
    def _metadata(db, identity):
        db.execute('INSERT OR IGNORE INTO session_metadata(session,updated) VALUES(?,?)', (identity, now()))

    def list(self, project_id, *, archived=False):
        if type(archived) is not bool:
            raise ValueError('Invalid archive selection')
        self.store.project(project_id)
        with self.store.connect() as db:
            return [dict(row) for row in db.execute('''
                SELECT s.*, COALESCE(meta.archived,0) AS archived,
                COALESCE(meta.last_read_message,0) AS last_read_message,
                meta.parent_session, meta.fork_message,
                COALESCE(meta.context_snapshot,'{}') AS context_snapshot,
                (SELECT COUNT(*) FROM messages m WHERE m.session=s.id AND m.role='assistant'
                 AND m.id>COALESCE(meta.last_read_message,0)) AS unread_count
                FROM sessions s LEFT JOIN session_metadata meta ON meta.session=s.id
                JOIN projects p ON p.id=s.project
                WHERE s.project=? AND p.owner=? AND COALESCE(meta.archived,0)=?
                ORDER BY s.created,s.id''', (project_id, self.store.owner, int(archived)))]

    def rename(self, identity, title):
        title = self._title(title)
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            self._session(db, identity)
            db.execute('UPDATE sessions SET title=? WHERE id=?', (title, identity))

    def draft(self, identity):
        with self.store.connect() as db:
            self._session(db, identity)
            row = db.execute('SELECT * FROM session_drafts WHERE session=?', (identity,)).fetchone()
            if row is None:
                return {'text': '', 'file_ids': [], 'submitted': False}
            return {'text': row['text'], 'file_ids': json.loads(row['file_ids']),
                    'submitted': bool(row['submitted'])}

    def save_draft(self, identity, text, file_ids, *, submitted=False):
        if (not isinstance(text, str) or len(text) > 12000 or type(submitted) is not bool
                or not isinstance(file_ids, list) or len(file_ids) > 100
                or any(not isinstance(item, str) for item in file_ids)
                or len(file_ids) != len(set(file_ids))):
            raise ValueError('Invalid conversation draft')
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            session = self._session(db, identity)
            for file_id in file_ids:
                if not db.execute('SELECT 1 FROM files WHERE id=? AND project=?',
                                  (file_id, session['project'])).fetchone():
                    raise PermissionError('Draft file belongs to a different project')
            db.execute('''INSERT INTO session_drafts(session,text,file_ids,submitted,updated)
                VALUES(?,?,?,?,?) ON CONFLICT(session) DO UPDATE SET
                text=excluded.text,file_ids=excluded.file_ids,submitted=excluded.submitted,updated=excluded.updated''',
                       (identity, text, json.dumps(file_ids), int(submitted), now()))

    def archive(self, identity, archived):
        if type(archived) is not bool:
            raise ValueError('Invalid archive state')
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            self._session(db, identity)
            if archived and db.execute("SELECT 1 FROM runs WHERE session=? AND state IN "
                                       "('queued','running','validating') LIMIT 1", (identity,)).fetchone():
                raise ValueError('Wait for active tasks before archiving')
            self._metadata(db, identity)
            db.execute('UPDATE session_metadata SET archived=?,updated=? WHERE session=?',
                       (int(archived), now(), identity))

    def mark_read(self, identity, message_id):
        if type(message_id) is not int or message_id < 0:
            raise ValueError('Invalid read cursor')
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            self._session(db, identity)
            if message_id and not db.execute('SELECT 1 FROM messages WHERE id=? AND session=?',
                                            (message_id, identity)).fetchone():
                raise PermissionError('Read cursor belongs to a different session')
            self._metadata(db, identity)
            db.execute('UPDATE session_metadata SET last_read_message=MAX(last_read_message,?),updated=? '
                       'WHERE session=?', (message_id, now(), identity))

    def fork(self, parent, message_id, title):
        from .branch_context import completed_references, fingerprint, read_results
        title = self._title(title)
        if type(message_id) is not int:
            raise ValueError('Invalid fork anchor')
        identity = uuid4().hex
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            source = self._session(db, parent)
            message = db.execute('SELECT * FROM messages WHERE id=? AND session=?',
                                 (message_id, parent)).fetchone()
            if message is None:
                raise PermissionError('Fork anchor belongs to a different session')
            # Anchor provenance only. No messages, attachments, pending actions,
            # confirmation receipts or instructions are copied into the child.
            content = json.dumps(dict(message), ensure_ascii=False, sort_keys=True)
            snapshot = {'schema_version': 1, 'source_message': {
                'id': message_id, 'sha256': sha256(content.encode('utf-8')).hexdigest()},
                'completed_facts': completed_references(db, parent, message['created'])}
            ancestor = db.execute('SELECT parent_session,context_snapshot FROM session_metadata WHERE session=?',
                                  (parent,)).fetchone()
            if ancestor is not None and ancestor['parent_session']:
                inherited = read_results(self, parent, _db=db, _ancestors=(identity,))
                if len(inherited) + len(snapshot['completed_facts']) > 100:
                    raise ValueError('Branch context exceeds 100 completed results')
                snapshot['ancestor_snapshot_sha256'] = fingerprint(json.loads(ancestor['context_snapshot']))
            db.execute('INSERT INTO sessions(id,project,title,created) VALUES(?,?,?,?)',
                       (identity, source['project'], title, now()))
            db.execute('INSERT INTO session_metadata(session,parent_session,fork_message,context_snapshot,updated) '
                       'VALUES(?,?,?,?,?)', (identity, parent, message_id,
                                             json.dumps(snapshot, ensure_ascii=False), now()))
        return identity

    def branch_results(self, identity):
        from .branch_context import read_results
        return read_results(self, identity)
