import httpx
import pytest

from asset_based_agent.report_review_app.services.remote_auth_service import (
    MemoryCredentialStore,
    RemoteSessionClient,
    ServerCapabilityUnavailable,
)


@pytest.mark.parametrize('mode', ['missing', 'future', 'supported', 'legacy'])
@pytest.mark.parametrize('method,capability,endpoint', [
    ('route_skill', 'skill_routing', '/skill-route'),
    ('create_review_job', 'review_jobs', '/review-jobs'),
    ('analyze_materials', 'material_analysis', '/material-analysis'),
])
def test_routing_checks_capability_before_any_paid_post(mode, method, capability, endpoint):
    calls = []
    def handler(request):
        calls.append((request.method, request.url.path))
        if request.url.path.endswith('/capabilities'):
            if mode == 'legacy':
                return httpx.Response(404)
            return httpx.Response(200, json={
                'schema_version': 999 if mode == 'future' else 1, 'protocol_version': 1,
                'capabilities': {capability: 1} if mode == 'supported' else {},
            })
        if request.url.path == '/openapi.json':
            return httpx.Response(200, json={'paths': {'/api/v1' + endpoint: {'post': {}}}})
        assert request.method == 'POST'
        return httpx.Response(200, json={'skill_id': 'synthetic'})
    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        client = RemoteSessionClient('https://test.example/api/v1', client_instance_id='synthetic',
                                     credential_store=MemoryCredentialStore(), http_client=http)
        client.access_token = 'synthetic'
        if mode in {'missing', 'future'}:
            with pytest.raises(ServerCapabilityUnavailable):
                getattr(client, method)({'prompt': 'synthetic'})
            assert all(method == 'GET' for method, _ in calls)
        else:
            assert getattr(client, method)({'prompt': 'synthetic'})['skill_id'] == 'synthetic'
            assert calls[-1] == ('POST', '/api/v1' + endpoint)
        assert calls[0] == ('GET', '/api/v1/capabilities')


def test_cancel_during_preflight_does_not_start_routing_call():
    import threading

    from asset_based_agent.report_review_app.services.task_cancellation import (
        TaskCancelled,
    )
    cancel = threading.Event()
    calls = []
    def handler(request):
        calls.append(request.method)
        cancel.set()
        return httpx.Response(200, json={'schema_version': 1, 'protocol_version': 1,
                                       'capabilities': {'skill_routing': 1}})
    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        client = RemoteSessionClient('https://test.example/api/v1', client_instance_id='synthetic',
                                     credential_store=MemoryCredentialStore(), http_client=http)
        client.access_token = 'synthetic'
        with pytest.raises(TaskCancelled):
            client.route_skill_cancellable({'prompt': 'synthetic'}, cancel)
    assert calls == ['GET']
