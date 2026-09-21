from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event
from types import SimpleNamespace

import pytest

from asset_based_agent.technical_platform.task_manager import TaskBinding, TaskManager


def worker():
    return SimpleNamespace(cancel=Event(), isRunning=lambda: False)


def test_update_barrier_blocks_new_work_without_cancelling_anything():
    manager = TaskManager()
    binding = TaskBinding('a', 'p', 's', 't')
    lease = manager.acquire_update_barrier()
    pending = worker()
    with pytest.raises(ValueError, match='update'):
        manager.register(binding, pending)
    assert not pending.cancel.is_set()
    manager.release_update_barrier(lease)
    manager.register(binding, pending)
    assert manager.active() == (binding,)


def test_registered_task_blocks_update_even_if_thread_has_just_finished():
    manager = TaskManager()
    binding = TaskBinding('a', 'p', 's', 't')
    pending = worker()
    manager.register(binding, pending)
    with pytest.raises(ValueError):
        manager.acquire_update_barrier()
    assert not pending.cancel.is_set()
    manager.finish(binding, pending)
    assert manager.acquire_update_barrier()


def test_stale_or_foreign_barrier_cannot_release_current_lease():
    manager = TaskManager()
    old = manager.acquire_update_barrier()
    with pytest.raises(ValueError):
        manager.acquire_update_barrier()
    manager.release_update_barrier(old)
    current = manager.acquire_update_barrier()
    assert current != old
    with pytest.raises(ValueError):
        manager.release_update_barrier(old)
    with pytest.raises(ValueError):
        manager.register(TaskBinding('a', 'p', 's', 't'), worker())
    manager.release_update_barrier(current)


def test_task_and_update_race_cannot_both_acquire():
    manager = TaskManager()
    barrier = Barrier(2)
    def task():
        barrier.wait(timeout=5)
        try:
            manager.register(TaskBinding('a', 'p', 's', 't'), worker())
            return True
        except ValueError:
            return False
    def update():
        barrier.wait(timeout=5)
        try:
            manager.acquire_update_barrier()
            return True
        except ValueError:
            return False
    with ThreadPoolExecutor(max_workers=2) as pool:
        a, b = pool.submit(task), pool.submit(update)
        assert sum([a.result(timeout=10), b.result(timeout=10)]) == 1


def test_office_resource_blocks_maintenance_without_interrupting_holder():
    from asset_based_agent.report_review_app.services.resource_locks import (
        ResourceLocks,
    )

    resources = ResourceLocks()
    with resources.lease(('office',)):
        with pytest.raises(ValueError), resources.update_barrier():
            pytest.fail('must not interrupt Office')
        assert resources.busy()
    with resources.update_barrier(), pytest.raises(ValueError), resources.lease(('office',)):
        pytest.fail('must not start Office during update')
    with resources.lease(('office',)):
        assert resources.busy()


def test_failed_update_preparation_releases_resource_barrier():
    from asset_based_agent.report_review_app.services.resource_locks import (
        ResourceLocks,
    )

    resources = ResourceLocks()
    with pytest.raises(RuntimeError), resources.update_barrier():
        raise RuntimeError('synthetic failure')
    with resources.lease(('model',)):
        assert resources.busy()

