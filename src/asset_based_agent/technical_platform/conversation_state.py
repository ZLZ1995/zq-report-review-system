"""Durable task clarification state; confirmed facts are not execution authority."""
from __future__ import annotations

import json
from uuid import uuid4

from .store import now

FACT_FIELDS = frozenset({'goal', 'scope', 'references', 'excluded', 'constraints', 'deliverables'})


class ConversationState:
    def __init__(self, store):
        self.store = store

    def _read(self, db, session):
        owned = db.execute(
            'SELECT s.id FROM sessions s JOIN projects p ON p.id=s.project '
            'WHERE s.id=? AND p.owner=?', (session, self.store.owner),
        ).fetchone()
        if not owned:
            raise PermissionError('Conversation is missing or belongs to another account')
        row = db.execute('SELECT * FROM conversation_state WHERE session=?', (session,)).fetchone()
        if row is None:
            return {'task_id': None, 'revision': 0, 'question': None, 'confirmed': {}, 'cancelled': False}
        if row['owner'] != self.store.owner:
            raise PermissionError('Conversation state belongs to another account')
        return {'task_id': row['task_id'], 'revision': row['revision'],
                'question': json.loads(row['question_json']) if row['question_json'] else None,
                'confirmed': json.loads(row['confirmed_json']), 'cancelled': bool(row['cancelled'])}

    def read(self, session):
        with self.store.connect() as db:
            return self._read(db, session)

    def _change(self, session, expected_revision, change, *, allow_new=False):
        if type(expected_revision) is not int or expected_revision < 0:
            raise ValueError('Invalid task revision')
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            state = self._read(db, session)
            if state['revision'] != expected_revision:
                raise ValueError('Task changed; refresh the current question')
            if not allow_new and (state['cancelled'] or not state['task_id']):
                raise ValueError('Task is absent or cancelled')
            state['revision'] += 1
            change(state)
            db.execute(
                'INSERT INTO conversation_state VALUES(?,?,?,?,?,?,?,?) '
                'ON CONFLICT(session) DO UPDATE SET task_id=excluded.task_id, '
                'revision=excluded.revision,question_json=excluded.question_json,'
                'confirmed_json=excluded.confirmed_json,cancelled=excluded.cancelled,updated=excluded.updated',
                (session, self.store.owner, state['task_id'], state['revision'],
                 json.dumps(state['question'], ensure_ascii=False) if state['question'] else None,
                 json.dumps(state['confirmed'], ensure_ascii=False), int(state['cancelled']), now()),
            )
            return state

    def start(self, session, *, expected_revision):
        def replace(state):
            state.update(task_id=uuid4().hex, question=None, confirmed={}, cancelled=False)
        return self._change(session, expected_revision, replace, allow_new=True)

    def execution_question(self, db, session, *, task_id, expected_revision, text, context):
        """Atomically hand off an execution question in its terminal transaction.

        A fresh understanding identity carries facts only, never old execution
        receipts. A newer conversation or repeated completion wins unchanged.
        """
        from ..agent_contracts import MessageRef
        if not db.in_transaction:
            raise ValueError('Execution handoff requires a transaction')
        if (type(expected_revision) is not int or expected_revision < 1
                or not isinstance(task_id, str) or not task_id):
            raise ValueError('Invalid execution conversation binding')
        messages = [MessageRef.model_validate(item).model_dump() for item in context]
        if (len(messages) > 9 or not isinstance(text, str)
                or not text.strip() or len(text) > 12000):
            raise ValueError('Execution clarification exceeds bounds')
        state = self._read(db, session)
        if (state['task_id'] != task_id or state['revision'] != expected_revision
                or not state['cancelled'] or state['question']):
            return False
        identity, revision = uuid4().hex, expected_revision + 1
        question = {'id': uuid4().hex, 'task_id': identity, 'revision': revision,
                    'text': text.strip(), 'context': messages}
        db.execute('UPDATE conversation_state SET task_id=?,revision=?,question_json=?, '
                   'confirmed_json=?,cancelled=0,updated=? WHERE session=? AND owner=?',
                   (identity, revision, json.dumps(question, ensure_ascii=False), '{}', now(),
                    session, self.store.owner))
        return True

    def resume(self, session, expected_revision):
        def resume(state):
            if not state['question']:
                raise ValueError('No pending clarification')
            state['question']['revision'] = state['revision']
        return self._change(session, expected_revision, resume)

    def ask(self, session, expected_revision, text, *, context=None):
        if not isinstance(text, str) or not text.strip() or len(text) > 12000:
            raise ValueError('Question must contain 1 to 12000 characters')
        from ..agent_contracts import MessageRef
        messages = [MessageRef.model_validate(item).model_dump() for item in (context or [])]
        if len(messages) > 9:
            raise ValueError('Clarification context exceeds bounds')

        def question(state):
            state['question'] = {'id': uuid4().hex, 'task_id': state['task_id'],
                                 'revision': state['revision'], 'text': text.strip()}
            if messages:
                state['question']['context'] = messages
        return self._change(session, expected_revision, question)

    def answer(self, session, expected_revision, question_id, facts):
        if not isinstance(facts, dict) or not facts or set(facts) - FACT_FIELDS:
            raise ValueError('Only task facts may be confirmed; grants and secrets are not accepted')
        for key, value in facts.items():
            values = [value] if key == 'goal' else value
            if (not isinstance(values, list) or len(values) > 100 or
                    any(not isinstance(item, str) or not item.strip() or len(item) > 4000 for item in values)):
                raise ValueError('Task facts require bounded text or lists of text, not nested objects')
        # Serialize before starting the transaction; reject non-JSON and unbounded data.
        encoded = json.dumps(facts, ensure_ascii=False, allow_nan=False)
        if len(encoded.encode('utf-8')) > 32000:
            raise ValueError('Confirmed task facts exceed the size limit')

        def answer(state):
            question = state['question']
            if (not question or question['id'] != question_id or
                    question['revision'] != expected_revision or question['task_id'] != state['task_id']):
                raise ValueError('Question is stale or belongs to another task')
            state['confirmed'].update(json.loads(encoded))
            if len(json.dumps(state['confirmed'], ensure_ascii=False).encode('utf-8')) > 32000:
                raise ValueError('Accumulated task facts exceed the size limit')
            state['question'] = None
        return self._change(session, expected_revision, answer)

    def cancel(self, session, expected_revision):
        def cancel(state):
            state.update(cancelled=True, question=None, confirmed={})
        return self._change(session, expected_revision, cancel)
