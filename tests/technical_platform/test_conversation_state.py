"""Pending questions are scoped, versioned, durable and never reusable grants."""
import pytest

from asset_based_agent.technical_platform.store import PlatformStore


def setup(tmp_path):
    from asset_based_agent.technical_platform.conversation_state import (
        ConversationState,
    )
    store = PlatformStore(tmp_path / 'state.sqlite', 'alice')
    project = store.create_project('synthetic')
    session = store.create_session(project)
    return store, session, ConversationState(store)


def test_pending_question_survives_restart(tmp_path):
    store, session, state = setup(tmp_path)
    current = state.start(session, expected_revision=0)
    pending = state.ask(session, current['revision'], 'Confirm selected files?')
    from asset_based_agent.technical_platform.conversation_state import (
        ConversationState,
    )
    reopened = ConversationState(PlatformStore(store.path, 'alice', create=False))
    assert reopened.read(session) == pending
    assert pending['question']['task_id'] == current['task_id']


def test_answer_requires_exact_question_and_revision_and_is_single_use(tmp_path):
    _, session, state = setup(tmp_path)
    current = state.start(session, expected_revision=0)
    pending = state.ask(session, current['revision'], 'Choose scope')
    question = pending['question']['id']
    with pytest.raises(ValueError):
        state.answer(session, pending['revision'], 'wrong', {'scope': ['f1']})
    answered = state.answer(session, pending['revision'], question, {'scope': ['f1']})
    assert answered['question'] is None
    assert answered['confirmed'] == {'scope': ['f1']}
    with pytest.raises(ValueError):
        state.answer(session, pending['revision'], question, {'scope': ['f1']})


def test_new_task_invalidates_question_and_confirmed_values(tmp_path):
    _, session, state = setup(tmp_path)
    current = state.start(session, expected_revision=0)
    pending = state.ask(session, current['revision'], 'Old task?')
    new = state.start(session, expected_revision=pending['revision'])
    assert new['task_id'] != current['task_id']
    assert new['confirmed'] == {}
    assert new['question'] is None
    with pytest.raises(ValueError):
        state.answer(session, pending['revision'], pending['question']['id'], {'yes': True})


def test_cancel_invalidates_pending_confirmation(tmp_path):
    _, session, state = setup(tmp_path)
    current = state.start(session, expected_revision=0)
    pending = state.ask(session, current['revision'], 'Generate?')
    cancelled = state.cancel(session, pending['revision'])
    assert cancelled['cancelled']
    assert cancelled['question'] is None
    with pytest.raises(ValueError):
        state.ask(session, cancelled['revision'], 'Reactivate?')


def test_cross_owner_and_cross_session_are_rejected(tmp_path):
    from asset_based_agent.technical_platform.conversation_state import (
        ConversationState,
    )
    store, session, state = setup(tmp_path)
    pending = state.ask(session, state.start(session, expected_revision=0)['revision'], 'A?')
    other = ConversationState(PlatformStore(store.path, 'bob', create=False))
    with pytest.raises(PermissionError):
        other.read(session)
    session_b = store.create_session(store.session(session)['project'])
    current_b = state.start(session_b, expected_revision=0)
    with pytest.raises(ValueError):
        state.answer(session_b, current_b['revision'], pending['question']['id'], {'yes': True})


def test_stale_writer_cannot_overwrite_newer_question(tmp_path):
    _, session, state = setup(tmp_path)
    current = state.start(session, expected_revision=0)
    first = state.ask(session, current['revision'], 'first')
    with pytest.raises(ValueError):
        state.ask(session, current['revision'], 'stale')
    assert state.read(session) == first


def test_answer_cannot_be_used_to_persist_execution_grants(tmp_path):
    _, session, state = setup(tmp_path)
    pending = state.ask(session, state.start(session, expected_revision=0)['revision'], 'Scope?')
    with pytest.raises(ValueError):
        state.answer(session, pending['revision'], pending['question']['id'], {'permissions': {'write': True}})
    assert state.read(session) == pending


def test_oversized_question_is_rejected_without_mutation(tmp_path):
    _, session, state = setup(tmp_path)
    current = state.start(session, expected_revision=0)
    with pytest.raises(ValueError):
        state.ask(session, current['revision'], 'x' * 12001)
    assert state.read(session) == current


def test_nested_grants_in_fact_fields_are_rejected(tmp_path):
    _, session, state = setup(tmp_path)
    pending = state.ask(session, state.start(session, expected_revision=0)['revision'], 'Scope?')
    with pytest.raises(ValueError):
        state.answer(session, pending['revision'], pending['question']['id'],
                     {'scope': {'permissions': {'modify_originals': True}}})
    assert state.read(session) == pending


def test_execution_question_resumes_context_once_without_authority(tmp_path):
    from asset_based_agent.technical_platform.agent_controller import AgentController
    store, session, state = setup(tmp_path)
    current = state.start(session, expected_revision=0)
    closed = state.cancel(session, current['revision'])
    context = [{'id': 'original', 'role': 'user', 'text': 'Inspect example.com; do not submit.'}]
    with store.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        assert state.execution_question(db, session, task_id=closed['task_id'],
            expected_revision=closed['revision'], text='Which page?', context=context)
    pending = state.read(session)
    assert pending['confirmed'] == {} and not pending['cancelled']
    assert pending['task_id'] != closed['task_id']
    reply = AgentController(store).prepare(session, 'The second one', model_id='test', selected_ids=[])
    assert [m.text for m in reply.request.context] == [context[0]['text'], 'Which page?']
    with store.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        assert not state.execution_question(db, session, task_id=closed['task_id'],
            expected_revision=closed['revision'], text='Late question', context=context)
    assert state.read(session)['revision'] == reply.revision


def test_execution_question_cannot_replace_new_task_or_survive_rollback(tmp_path):
    store, session, state = setup(tmp_path)
    current = state.start(session, expected_revision=0)
    closed = state.cancel(session, current['revision'])
    with pytest.raises(RuntimeError), store.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        state.execution_question(db, session, task_id=closed['task_id'],
            expected_revision=closed['revision'], text='Which?', context=[])
        raise RuntimeError('synthetic persistence failure')
    assert state.read(session) == closed
    new = state.start(session, expected_revision=closed['revision'])
    with store.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        assert not state.execution_question(db, session, task_id=closed['task_id'],
            expected_revision=closed['revision'], text='Late?', context=[])
    assert state.read(session) == new


@pytest.mark.parametrize('change', ['oversize', 'foreign', 'not_closed'])
def test_execution_question_fails_closed(tmp_path, change):
    from asset_based_agent.technical_platform.conversation_state import (
        ConversationState,
    )
    store, session, state = setup(tmp_path)
    current = state.start(session, expected_revision=0)
    if change != 'not_closed':
        current = state.cancel(session, current['revision'])
    service = (ConversationState(PlatformStore(store.path, 'bob', create=False))
               if change == 'foreign' else state)
    context = [{'id': str(i), 'role': 'user', 'text': 'restriction'} for i in range(10)] if change == 'oversize' else []
    with store.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        if change == 'not_closed':
            assert not service.execution_question(db, session, task_id=current['task_id'],
                expected_revision=current['revision'], text='Which?', context=context)
        else:
            with pytest.raises((ValueError, PermissionError)):
                service.execution_question(db, session, task_id=current['task_id'],
                    expected_revision=current['revision'], text='Which?', context=context)
    assert state.read(session) == current
