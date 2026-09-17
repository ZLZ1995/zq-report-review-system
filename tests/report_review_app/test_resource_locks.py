from threading import Event, Thread

import httpx
import pytest

from asset_based_agent.report_review_app.services.task_cancellation import (
    TaskCancelled,
    cancellable_call,
)


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
