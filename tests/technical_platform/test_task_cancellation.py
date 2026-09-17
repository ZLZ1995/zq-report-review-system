from threading import Event, Thread

import httpx


def test_material_request_uses_single_api_prefix():
    from asset_based_agent.report_review_app.services.remote_auth_service import (
        MemoryCredentialStore,
        RemoteSessionClient,
    )
    def respond(request):
        if request.method == 'GET':
            assert request.url.path == '/api/v1/capabilities'
            return httpx.Response(200, json={'schema_version': 1, 'protocol_version': 1,
                                           'capabilities': {'material_analysis': 1}})
        assert request.url.path == '/api/v1/material-analysis'
        return httpx.Response(200, json={'assignments': []})
    client = RemoteSessionClient('https://example.test/api/v1', client_instance_id='test',
        credential_store=MemoryCredentialStore(), http_client=httpx.Client(transport=httpx.MockTransport(respond)))
    client.access_token = 'test'
    assert client.analyze_materials({'files': []}) == {'assignments': []}


def test_blocked_call_can_be_cancelled_without_waiting_for_response():
    from asset_based_agent.report_review_app.services.task_cancellation import (
        TaskCancelled,
        cancellable_call,
    )
    cancel, entered, release, finished = Event(), Event(), Event(), Event()
    observed = []
    def call():
        entered.set()
        release.wait(5)
        return 'late'
    def run():
        try:
            cancellable_call(call, cancel)
        except TaskCancelled:
            observed.append('cancelled')
        finally:
            finished.set()
    thread = Thread(target=run)
    thread.start()
    try:
        assert entered.wait(1)
        cancel.set()
        assert finished.wait(1)
        assert observed == ['cancelled']
    finally:
        release.set()
        thread.join(2)


def test_review_cancellation_interrupts_poll_and_requests_server_stop():
    from asset_based_agent.report_review_app.services.remote_review_llm import (
        RemoteReviewLlm,
    )
    from asset_based_agent.report_review_app.services.task_cancellation import (
        TaskCancelled,
    )
    started, release, stopped, finished = Event(), Event(), Event(), Event()
    class Client:
        def execute_review_job(self, identity):
            release.wait(5)
            return {'status': 'succeeded', 'issues': []}
        def get_review_job(self, identity):
            started.set()
            release.wait(5)
            return {'status': 'running'}
        def cancel_review_job(self, identity):
            assert identity == 'job'
            stopped.set()
    provider = RemoteReviewLlm(Client())
    provider.cancel_event = Event()
    def run():
        try:
            provider._execute_with_progress('job', 2, None)
        except TaskCancelled:
            finished.set()
    worker = Thread(target=run)
    worker.start()
    try:
        assert started.wait(1)
        provider.cancel_event.set()
        assert finished.wait(1)
        assert stopped.wait(1)
    finally:
        release.set()
        worker.join(2)
