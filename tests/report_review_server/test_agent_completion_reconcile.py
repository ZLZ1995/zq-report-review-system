"""S2-03 服务端对账端点：GET /api/v1/agent/completions/{client_request_id}（先红后绿）。"""
from __future__ import annotations

from asset_based_agent.report_review_server.services.agent_completion_service import (
    AgentCompletionService,
)
from asset_based_agent.report_review_server.services.provider_gateway import (
    ProviderCallError,
)

from .conftest import bearer
from .test_agent_completion_stream import (
    _admin_and_user,
    _collect,
    _db,
    _install_provider,
    _setup_billable,
    _stream,
    _text_script,
)


def _query(client, token, request_id):
    return client.get(f'/api/v1/agent/completions/{request_id}',
                      headers=bearer(token))


def test_reconcile_endpoint_reports_succeeded_with_replay(client):
    admin, user = _admin_and_user(client)
    model = _setup_billable(client, admin, user)
    _install_provider(client, [_text_script('对账回答')])
    token = str(user['access_token'])
    with _stream(client, token, model['model_id'], 'req-rec-1') as response:
        events = _collect(response)
    receipt = events[-1][1]
    result = _query(client, token, 'req-rec-1')
    assert result.status_code == 200, result.text
    body = result.json()
    assert body['status'] == 'succeeded'
    assert body['billing_request_id'] == receipt['billing_request_id']
    assert body['replay_available'] is True
    assert body['error_code'] in ('', None)


def test_reconcile_endpoint_reports_failed(client):
    admin, user = _admin_and_user(client)
    model = _setup_billable(client, admin, user)
    _install_provider(client, [ProviderCallError(
        'provider_http_error', '渠道 500', retryable=False)])
    token = str(user['access_token'])
    with _stream(client, token, model['model_id'], 'req-rec-2') as response:
        _collect(response)
    result = _query(client, token, 'req-rec-2')
    assert result.status_code == 200, result.text
    body = result.json()
    assert body['status'] == 'failed'
    assert body['replay_available'] is False
    assert body['error_code'] == 'provider_http_error'


def test_reconcile_endpoint_reports_uncertain(client):
    admin, user = _admin_and_user(client)
    model = _setup_billable(client, admin, user)
    _install_provider(client, [ProviderCallError(
        'provider_usage_missing', '用量缺失', retryable=False)])
    token = str(user['access_token'])
    with _stream(client, token, model['model_id'], 'req-rec-3') as response:
        _collect(response)
    result = _query(client, token, 'req-rec-3')
    assert result.status_code == 200, result.text
    body = result.json()
    assert body['status'] == 'uncertain'
    assert body['replay_available'] is False


def test_reconcile_endpoint_reports_streaming_in_progress(client):
    admin, user = _admin_and_user(client)
    model = _setup_billable(client, admin, user)
    token = str(user['access_token'])
    with _db(client) as db:
        service = AgentCompletionService(
            client.app.state.review_job_service.metered,
            client.app.state.session_factory)
        prepared = service.begin(
            db, user_id=user['user']['user_id'], model_id=model['model_id'],
            client_request_id='req-rec-4',
            messages=[{'role': 'user', 'content': '你好'}], tools=[],
            sampling={})
        assert not isinstance(prepared, dict)
    result = _query(client, token, 'req-rec-4')
    assert result.status_code == 200, result.text
    body = result.json()
    assert body['status'] == 'streaming'
    assert body['replay_available'] is False


def test_reconcile_endpoint_404_for_unknown_or_foreign_request(client):
    admin, user = _admin_and_user(client)
    model = _setup_billable(client, admin, user)
    _install_provider(client, [_text_script('隔离')])
    token = str(user['access_token'])
    with _stream(client, token, model['model_id'], 'req-rec-5') as response:
        _collect(response)
    # 不存在的 client_request_id
    assert _query(client, token, 'req-never-seen').status_code == 404
    # 其他用户的 client_request_id 不得可见
    other = client.post(
        '/api/v1/admin/users', headers=bearer(str(admin['access_token'])),
        json={'username': 'stream-other', 'display_name': 'Other',
              'temporary_password': 'Temporary123'})
    assert other.status_code == 201
    from .conftest import login
    other_user = login(client, 'stream-other', 'Temporary123',
                       instance='other-desktop')
    foreign = _query(client, str(other_user['access_token']), 'req-rec-5')
    assert foreign.status_code == 404


# ------------------------------------------------------------------ 对账回放端点

def test_replay_endpoint_returns_stored_events(client):
    admin, user = _admin_and_user(client)
    model = _setup_billable(client, admin, user)
    _install_provider(client, [_text_script('回放内容')])
    token = str(user['access_token'])
    with _stream(client, token, model['model_id'], 'req-replay-1') as response:
        _collect(response)
    result = client.get('/api/v1/agent/completions/req-replay-1/replay',
                        headers=bearer(token))
    assert result.status_code == 200, result.text
    body = result.json()
    kinds = [event['kind'] for event in body['events']]
    assert 'text_delta' in kinds
    texts = [event['data'].get('text', '') for event in body['events']
             if event['kind'] == 'text_delta']
    assert ''.join(texts) == '回放内容'
    assert body['billing_request_id']


def test_replay_endpoint_rejects_uncertain(client):
    admin, user = _admin_and_user(client)
    model = _setup_billable(client, admin, user)
    _install_provider(client, [ProviderCallError(
        'provider_usage_missing', '用量缺失', retryable=False)])
    token = str(user['access_token'])
    with _stream(client, token, model['model_id'], 'req-replay-2') as response:
        _collect(response)
    result = client.get('/api/v1/agent/completions/req-replay-2/replay',
                        headers=bearer(token))
    assert result.status_code == 409, result.text


def test_replay_endpoint_404_for_unknown(client):
    _admin, user = _admin_and_user(client)
    result = client.get('/api/v1/agent/completions/req-nothing/replay',
                        headers=bearer(str(user['access_token'])))
    assert result.status_code == 404
