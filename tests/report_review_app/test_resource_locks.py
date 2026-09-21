import multiprocessing
from pathlib import Path
from threading import Event, Thread

import httpx
import pytest

from asset_based_agent.report_review_app.services.task_cancellation import (
    TaskCancelled,
    cancellable_call,
)


def _hold_cross_process_lease(lock_root: str, resource: str, ready, release) -> None:
    from asset_based_agent.report_review_app.services.resource_locks import (
        ResourceLocks,
    )

    resources = ResourceLocks(process_lock_root=Path(lock_root))
    with resources.lease((resource,)):
        ready.set()
        release.wait(10)


def _enter_cross_process_lease(lock_root: str, resource: str, entered) -> None:
    from asset_based_agent.report_review_app.services.resource_locks import (
        ResourceLocks,
    )

    resources = ResourceLocks(process_lock_root=Path(lock_root))
    with resources.lease((resource,)):
        entered.set()


@pytest.mark.parametrize('resource', ['office', 'output:synthetic'])
def test_exclusive_lease_is_shared_across_client_processes(tmp_path, resource):
    context = multiprocessing.get_context('spawn')
    ready, release, entered = context.Event(), context.Event(), context.Event()
    owner = context.Process(
        target=_hold_cross_process_lease,
        args=(str(tmp_path), resource, ready, release),
    )
    waiter = context.Process(
        target=_enter_cross_process_lease,
        args=(str(tmp_path), resource, entered),
    )
    owner.start()
    try:
        assert ready.wait(5)
        waiter.start()
        assert not entered.wait(.3)
        release.set()
        assert entered.wait(5)
        waiter.join(5)
        owner.join(5)
        assert waiter.exitcode == 0
        assert owner.exitcode == 0
    finally:
        release.set()
        for process in (waiter, owner):
            if process.pid is not None and process.is_alive():
                process.terminate()
            if process.pid is not None:
                process.join(2)


def test_model_capacity_two_is_shared_across_client_processes(tmp_path):
    context = multiprocessing.get_context('spawn')
    first_ready, second_ready = context.Event(), context.Event()
    release, third_entered = context.Event(), context.Event()
    owners = [
        context.Process(
            target=_hold_cross_process_lease,
            args=(str(tmp_path), 'model', ready, release),
        )
        for ready in (first_ready, second_ready)
    ]
    waiter = context.Process(
        target=_enter_cross_process_lease,
        args=(str(tmp_path), 'model', third_entered),
    )
    for owner in owners:
        owner.start()
    try:
        assert first_ready.wait(5) and second_ready.wait(5)
        waiter.start()
        assert not third_entered.wait(.3)
        release.set()
        assert third_entered.wait(5)
        for process in (*owners, waiter):
            process.join(5)
            assert process.exitcode == 0
    finally:
        release.set()
        for process in (*owners, waiter):
            if process.pid is not None and process.is_alive():
                process.terminate()
            if process.pid is not None:
                process.join(2)


def test_process_lock_setup_failure_releases_local_reservation(tmp_path):
    from asset_based_agent.report_review_app.services.resource_locks import (
        ResourceLocks,
    )

    lock_root = tmp_path / 'not-a-directory'
    lock_root.write_text('synthetic blocker', encoding='ascii')
    resources = ResourceLocks(process_lock_root=lock_root)
    with pytest.raises(OSError), resources.lease(('office',)):
        pytest.fail('an invalid process lock root must not execute')
    assert not resources.busy()


def test_waiting_cancel_does_not_release_another_office_lease():
    from asset_based_agent.report_review_app.services.resource_locks import (
        ResourceLocks,
    )
    resources = ResourceLocks()
    cancel, done = Event(), Event()
    results = []
    def wait():
        try:
            with resources.lease(('office',), cancel):
                results.append('entered')
        except TaskCancelled:
            results.append('cancelled')
        finally:
            done.set()
    with resources.lease(('office',)):
        thread = Thread(target=wait)
        thread.start()
        cancel.set()
        assert done.wait(2)
        assert results == ['cancelled']
    thread.join(2)
    with resources.lease(('office',)):
        pass


def test_invalid_resource_and_exception_release():
    from asset_based_agent.report_review_app.services.resource_locks import (
        ResourceLocks,
    )
    resources = ResourceLocks()
    with pytest.raises(ValueError), resources.lease(('unregistered',)):
        pytest.fail('unknown resources must not execute')
    with pytest.raises(RuntimeError), resources.lease(('office', 'output:synthetic')):
        raise RuntimeError('synthetic')
    with resources.lease(('office', 'output:synthetic')):
        pass


def test_model_limit_is_held_by_real_request_and_cancelled_waiter_never_posts():
    from asset_based_agent.report_review_app.services.remote_auth_service import (
        MemoryCredentialStore,
        RemoteSessionClient,
    )
    from asset_based_agent.report_review_app.services.resource_locks import (
        CLIENT_RESOURCES,
    )
    entered, release, done = Event(), Event(), Event()
    calls, errors = [], []
    def respond(request):
        calls.append(request.url.path)
        entered.set()
        assert release.wait(5)
        return httpx.Response(200, json={'status': 'succeeded'})
    client = RemoteSessionClient('https://example.test/api/v1', client_instance_id='synthetic',
        credential_store=MemoryCredentialStore(), http_client=httpx.Client(transport=httpx.MockTransport(respond)))
    client.access_token = 'synthetic'
    cancel, owner_cancel, owner_done = Event(), Event(), Event()
    def owner():
        try:
            cancellable_call(lambda: client.execute_review_job('first'), owner_cancel)
        except TaskCancelled:
            owner_done.set()
    def queued():
        try:
            client.execute_review_job_cancellable('second', cancel)
        except TaskCancelled:
            errors.append('cancelled')
        finally:
            done.set()
    with CLIENT_RESOURCES.lease(('model',)):
        active = Thread(target=owner)
        active.start()
        try:
            assert entered.wait(2)
            owner_cancel.set()
            assert owner_done.wait(2)
            active.join(2)
            assert not active.is_alive()
            waiting = Thread(target=queued)
            waiting.start()
            cancel.set()
            assert done.wait(2)
            assert errors == ['cancelled']
            assert calls == ['/api/v1/review-jobs/first/execute']
        finally:
            release.set()
            active.join(3)
            if 'waiting' in locals():
                waiting.join(3)
            # Synchronize with the HTTP thread's lease release, not just its caller.
            with CLIENT_RESOURCES.lease(('model',)):
                pass
    client.http_client.close()


def test_model_resource_allows_two_calls_and_blocks_the_third():
    from asset_based_agent.report_review_app.services.resource_locks import (
        ResourceLocks,
    )

    resources = ResourceLocks()
    release = Event()
    entered = [Event(), Event(), Event()]

    def use_slot(index):
        with resources.lease(("model",)):
            entered[index].set()
            release.wait(5)

    workers = [Thread(target=use_slot, args=(index,)) for index in range(3)]
    for worker in workers[:2]:
        worker.start()
    assert entered[0].wait(2) and entered[1].wait(2)
    workers[2].start()
    assert not entered[2].wait(0.2)
    release.set()
    assert entered[2].wait(2)
    for worker in workers:
        worker.join(2)
        assert not worker.is_alive()
