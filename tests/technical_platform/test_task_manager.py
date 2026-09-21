from dataclasses import FrozenInstanceError
from threading import Event

import pytest

from asset_based_agent.technical_platform.task_manager import TaskBinding, TaskManager


class Worker:
    def __init__(self):
        self.cancel = Event()
        self.running = False

    def isRunning(self):
        return self.running


def binding(task='one', session='chat', owner='alice'):
    return TaskBinding(owner, 'project', session, task)


def test_cancel_is_bound_to_exact_account_project_session_task():
    manager = TaskManager()
    first, second = Worker(), Worker()
    manager.register(binding(), first)
    manager.register(binding('two', 'other'), second)
    assert not manager.cancel(binding(owner='bob'))
    assert manager.cancel(binding())
    assert first.cancel.is_set()
    assert not second.cancel.is_set()
    assert manager.active() == (binding(), binding('two', 'other'))


def test_duplicate_worker_task_and_active_session_are_rejected():
    manager = TaskManager()
    worker = Worker()
    manager.register(binding(), worker)
    for scope, candidate in [(binding(), Worker()), (binding('two'), Worker()),
                             (binding('two', 'other'), worker)]:
        with pytest.raises(ValueError):
            manager.register(scope, candidate)
    assert manager.active() == (binding(),)


def test_finished_requires_matching_worker_and_thread_termination():
    manager = TaskManager()
    worker = Worker()
    manager.register(binding(), worker)
    assert not manager.finish(binding(), Worker())
    worker.running = True
    with pytest.raises(ValueError):
        manager.finish(binding(), worker)
    assert manager.active() == (binding(),)
    worker.running = False
    assert manager.finish(binding(), worker)
    replacement = Worker()
    manager.register(binding(), replacement)
    assert not manager.finish(binding(), worker)
    assert manager.cancel(binding())
    assert replacement.cancel.is_set()


def test_binding_is_immutable_and_nonempty():
    scope = binding()
    with pytest.raises(FrozenInstanceError):
        scope.session_id = 'changed'
    with pytest.raises(ValueError):
        TaskBinding('', 'project', 'session', 'task')


def test_cancel_all_keeps_workers_until_their_finished_signal():
    manager = TaskManager()
    first, second = Worker(), Worker()
    manager.register(binding(), first)
    manager.register(binding('two', 'other'), second)
    assert manager.cancel_all() == 2
    assert first.cancel.is_set() and second.cancel.is_set()
    assert len(manager.active()) == 2
