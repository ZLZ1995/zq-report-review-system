from dataclasses import replace
from threading import Event
from types import SimpleNamespace

import pytest

from asset_based_agent.technical_platform.task_manager import TaskBinding, TaskManager


def setup():
    from asset_based_agent.technical_platform.browser_task_leases import (
        BrowserTaskLeases,
    )
    page, other = object(), object()
    session = SimpleNamespace(owner='alice', owns_page=lambda p: p is page or p is other)
    manager = TaskManager()
    worker = SimpleNamespace(cancel=Event(), isRunning=lambda: True)
    binding = TaskBinding('alice', 'p', 's', 't')
    manager.register(binding, worker)
    leases = BrowserTaskLeases(session, manager)
    leases.register(page); leases.register(other)
    return leases, page, other, binding, worker, manager


def test_tab_lease_is_exclusive_and_requires_live_owned_worker():
    leases, page, other, binding, worker, manager = setup()
    with pytest.raises(PermissionError): leases.acquire(page, binding, worker, confirmed=False)
    lease = leases.acquire(page, binding, worker, confirmed=True)
    assert leases.valid(lease)
    with pytest.raises(PermissionError): leases.acquire(page, binding, worker, confirmed=True)
    second = SimpleNamespace(cancel=Event(), isRunning=lambda: True)
    second_binding = TaskBinding('alice', 'p', 's2', 't2')
    manager.register(second_binding, second)
    with pytest.raises(PermissionError): leases.acquire(page, second_binding, second, confirmed=True)
    separate = leases.acquire(other, second_binding, second, confirmed=True)
    worker.cancel.set()
    assert not leases.valid(lease) and leases.valid(separate)
    with pytest.raises(PermissionError): leases.acquire(page, binding, worker, confirmed=True)


def test_takeover_forgery_release_and_close_never_revive_old_lease():
    leases, page, _, binding, worker, _ = setup()
    lease = leases.acquire(page, binding, worker, confirmed=True)
    assert not leases.valid(replace(lease))
    leases.takeover(page)
    assert not leases.valid(lease)
    renewed = leases.acquire(page, binding, worker, confirmed=True)
    leases.release(lease)
    assert leases.valid(renewed)
    leases.unregister(page)
    assert not leases.valid(renewed)
    with pytest.raises(PermissionError): leases.acquire(page, binding, worker, confirmed=True)
    leases.close()
    with pytest.raises(PermissionError): leases.register(page)


def test_wrong_owner_unregistered_worker_and_finished_task_reject():
    leases, page, _, binding, worker, _ = setup()
    with pytest.raises(PermissionError):
        leases.acquire(page, replace(binding, owner='bob'), worker, confirmed=True)
    with pytest.raises(PermissionError):
        leases.acquire(object(), binding, worker, confirmed=True)
    with pytest.raises(PermissionError):
        leases.acquire(page, binding, SimpleNamespace(cancel=Event(), isRunning=lambda: True), confirmed=True)
    worker.isRunning = lambda: False
    with pytest.raises(PermissionError): leases.acquire(page, binding, worker, confirmed=True)


def test_revoke_all_invalidates_every_active_tab_lease():
    leases, page, other, binding, worker, manager = setup()
    first = leases.acquire(page, binding, worker, confirmed=True)
    second_worker = SimpleNamespace(cancel=Event(), isRunning=lambda: True)
    second_binding = TaskBinding('alice', 'p', 's2', 't2')
    manager.register(second_binding, second_worker)
    second = leases.acquire(other, second_binding, second_worker, confirmed=True)

    assert leases.revoke_all() == 2
    assert not leases.valid(first)
    assert not leases.valid(second)
