"""S06：流式 agent completion 端点——计费、幂等、断线对账、allowlist。"""
from __future__ import annotations

import json
from decimal import Decimal

from sqlalchemy import select

from asset_based_agent.report_review_server.models import (
    AuthSession,
    BalanceHold,
    BillingRequest,
    ProviderAttempt,
    WalletLedger,
)
from asset_based_agent.report_review_server.services.agent_completion_service import (
    AgentCompletionService,
    PreparedStream,
)
from asset_based_agent.report_review_server.services.provider_gateway import (
    ProviderCallError,
)

from .conftest import bearer, login

# ------------------------------------------------------------------ 假流式 provider

class FakeStreamingProvider:
    """按脚本回放归一化流事件；脚本项为异常实例时抛出。"""

    def __init__(self, scripts):
        self.scripts = list(scripts)
        self.payloads = []

    def call(self, route, payload):
        raise AssertionError('非流式路径不得被调用')

    def stream(self, route, payload):
        self.payloads.append(payload)
        script = self.scripts.pop(0)
        if isinstance(script, BaseException):
            raise script
        for item in script:
            if isinstance(item, BaseException):
                raise item
            yield item


def _text_script(text, *, input_tokens=10, output_tokens=5):
    return [
        {'kind': 'message_start', 'data': {}},
        {'kind': 'text_delta', 'data': {'text': text}},
        {'kind': 'usage', 'data': {'input_tokens': input_tokens,
                                   'output_tokens': output_tokens}},
        {'kind': 'message_complete', 'data': {}},
    ]


# ------------------------------------------------------------------ 数据准备

def _admin_and_user(client):
    admin = login(client, 'admin', 'AdminPassword123!', instance='admin-desktop')
    created = client.post(
        '/api/v1/admin/users', headers=bearer(str(admin['access_token'])),
        json={'username': 'stream-user', 'display_name': 'Stream User',
              'temporary_password': 'Temporary123'})
    assert created.status_code == 201, created.text
    user = login(client, 'stream-user', 'Temporary123', instance='stream-desktop')
    return admin, user


def _setup_billable(client, admin, user, *, balance='50.00000000'):
    admin_token = str(admin['access_token'])
    model = client.post(
        '/api/v1/admin/models', headers=bearer(admin_token),
        json={'code': 'stream-model', 'display_name': 'Stream Model',
              'tier': 'standard', 'model_multiplier': '1',
              'max_output_tokens': 8192}).json()
    route = client.post(
        f"/api/v1/admin/models/{model['model_id']}/routes",
        headers=bearer(admin_token),
        json={'provider_type': 'deepseek', 'provider_model': 'stream-model',
              'base_url': 'https://example.com', 'api_key': 'secret',
              'priority': 1,
              'rates': dict.fromkeys(
                  ['input', 'output', 'cache_hit', 'cache_miss', 'reasoning'],
                  '1')})
    assert route.status_code == 201, route.text
    adjusted = client.post(
        f"/api/v1/admin/users/{user['user']['user_id']}/balance-adjustments",
        headers=bearer(admin_token), json={'amount': balance})
    assert adjusted.status_code == 200
    return model


def _install_provider(client, scripts):
    fake = FakeStreamingProvider(scripts)
    client.app.state.review_job_service.metered.provider_client = fake
    return fake


def _stream(client, token, model_id, request_id, messages=None, tools=None,
            protocol_version=1):
    payload = {
        'protocol_version': protocol_version,
        'client_version': '0.3.0',
        'model_id': model_id,
        'client_request_id': request_id,
        'messages': messages or [{'role': 'user', 'content': '你好'}],
        'tools': tools or [],
        'sampling': {},
    }
    return client.stream(
        'POST', '/api/v1/agent/completions/stream',
        headers=bearer(token), json=payload)


def _collect(response):
    events = []
    event, data = None, []
    for line in response.iter_lines():
        if line.startswith('event: '):
            event = line[7:]
        elif line.startswith('data: '):
            data.append(line[6:])
        elif line == '' and event is not None:
            events.append((event, json.loads(''.join(data))))
            event, data = None, []
    return events


def _db(client):
    return client.app.state.session_factory()


# ------------------------------------------------------------------ 全绿链路

def test_streaming_completion_full_green(client):
    admin, user = _admin_and_user(client)
    model = _setup_billable(client, admin, user)
    _install_provider(client, [_text_script('流式回答')])
    token = str(user['access_token'])
    with _stream(client, token, model['model_id'], 'req-green-1') as response:
        assert response.status_code == 200
        assert response.headers['content-type'].startswith('text/event-stream')
        events = _collect(response)
    kinds = [kind for kind, _ in events]
    assert kinds == ['message_start', 'text_delta', 'usage',
                     'message_complete', 'receipt']
    receipt = events[-1][1]
    assert Decimal(receipt['charged_amount']) > 0
    assert receipt['replayed'] is False
    with _db(client) as db:
        billing = db.scalar(select(BillingRequest).where(
            BillingRequest.client_request_id == 'req-green-1'))
        assert billing.status == 'succeeded'
        attempt = db.scalar(select(ProviderAttempt).where(
            ProviderAttempt.billing_request_id == billing.billing_request_id))
        assert attempt.status == 'succeeded'
        assert attempt.input_tokens == 10 and attempt.output_tokens == 5
        charges = db.scalars(select(WalletLedger).where(
            WalletLedger.reference_id == billing.billing_request_id)).all()
        assert len(charges) == 1, '必须只结算一次'
        hold = db.get(BalanceHold, billing.hold_id)
        assert hold.status == 'captured'


def test_same_request_id_replays_without_double_charge(client):
    admin, user = _admin_and_user(client)
    model = _setup_billable(client, admin, user)
    fake = _install_provider(client, [_text_script('只算一次')])
    token = str(user['access_token'])
    with _stream(client, token, model['model_id'], 'req-idem-1') as first:
        first_events = _collect(first)
    with _stream(client, token, model['model_id'], 'req-idem-1') as second:
        second_events = _collect(second)
    assert len(fake.payloads) == 1, '重试不得再次调用 provider'
    assert [k for k, _ in second_events] == [k for k, _ in first_events]
    assert second_events[-1][1]['replayed'] is True
    with _db(client) as db:
        billing = db.scalar(select(BillingRequest).where(
            BillingRequest.client_request_id == 'req-idem-1'))
        charges = db.scalars(select(WalletLedger).where(
            WalletLedger.reference_id == billing.billing_request_id)).all()
        assert len(charges) == 1, '同 request ID 重试不重复计费'


def test_idempotency_conflict_on_different_payload(client):
    admin, user = _admin_and_user(client)
    model = _setup_billable(client, admin, user)
    _install_provider(client, [_text_script('甲')])
    token = str(user['access_token'])
    with _stream(client, token, model['model_id'], 'req-conflict-1'):
        pass
    with _stream(client, token, model['model_id'], 'req-conflict-1',
                 messages=[{'role': 'user', 'content': '不同的内容'}]) as response:
        response.read()
        assert response.status_code == 409
        assert response.json()['error']['code'] == 'idempotency_conflict'


# ------------------------------------------------------------------ 失败与对账

def test_provider_failure_releases_hold_with_structured_error(client):
    admin, user = _admin_and_user(client)
    model = _setup_billable(client, admin, user)
    _install_provider(client, [ProviderCallError(
        'provider_auth_failed', 'bad key', retryable=False)])
    token = str(user['access_token'])
    with _stream(client, token, model['model_id'], 'req-fail-1') as response:
        events = _collect(response)
    assert events[-1][0] == 'error'
    assert events[-1][1]['code'] == 'provider_auth_failed'
    with _db(client) as db:
        billing = db.scalar(select(BillingRequest).where(
            BillingRequest.client_request_id == 'req-fail-1'))
        assert billing.status == 'failed'
        hold = db.get(BalanceHold, billing.hold_id)
        assert hold.status == 'released', '无用量失败必须释放冻结'
        charges = db.scalars(select(WalletLedger).where(
            WalletLedger.reference_id == billing.billing_request_id)).all()
        assert charges == []


def test_uncertain_outcome_requires_reconciliation(client):
    admin, user = _admin_and_user(client)
    model = _setup_billable(client, admin, user)
    _install_provider(client, [ProviderCallError(
        'provider_network_error', '连接中断', retryable=True, usage=None)])
    token = str(user['access_token'])
    with _stream(client, token, model['model_id'], 'req-uncertain-1') as response:
        events = _collect(response)
    assert events[-1][0] == 'error'
    assert events[-1][1]['code'] == 'billing_reconciliation_required'
    with _db(client) as db:
        billing = db.scalar(select(BillingRequest).where(
            BillingRequest.client_request_id == 'req-uncertain-1'))
        assert billing.status == 'uncertain'
    with _stream(client, token, model['model_id'], 'req-after-uncertain') as response:
        response.read()
        assert response.status_code == 409
        assert response.json()['error']['code'] == 'billing_reconciliation_required'


def test_disconnect_marks_reconcilable_state(client):
    """客户端断线（GeneratorExit）必须留下可对账状态。

    服务层直连：TestClient 的 response.close() 无法及时把 GeneratorExit 注入
    threadpool 中的流式生成器（传输层限制，已记入台账），因此直接在服务层
    关闭生成器来模拟客户端断线。
    """
    admin, user = _admin_and_user(client)
    model = _setup_billable(client, admin, user)
    _install_provider(client, [_text_script('被中断的回答')])
    service = AgentCompletionService(
        metered=client.app.state.review_job_service.metered,
        session_factory=client.app.state.session_factory)
    db = _db(client)
    try:
        prepared = service.begin(
            db, user_id=user['user']['user_id'], model_id=model['model_id'],
            client_request_id='req-disconnect-1',
            messages=[{'role': 'user', 'content': '你好'}],
            tools=[], sampling={})
        assert isinstance(prepared, PreparedStream)
        gen = service.stream(db, prepared)
        first = next(gen)
        assert first['kind'] == 'message_start'
        gen.close()  # 模拟客户端断线：GeneratorExit 注入流式生成器
    finally:
        db.close()
    with _db(client) as db:
        billing = db.scalar(select(BillingRequest).where(
            BillingRequest.client_request_id == 'req-disconnect-1'))
        assert billing.status == 'disconnected', '断线必须留下可对账状态'
        assert billing.error_code == 'client_disconnected'
        hold = db.get(BalanceHold, billing.hold_id)
        assert hold.status == 'released', '未知用量的断线必须释放冻结'


# ------------------------------------------------------------------ 请求校验

def test_invalid_tool_schema_rejected(client):
    admin, user = _admin_and_user(client)
    model = _setup_billable(client, admin, user)
    token = str(user['access_token'])
    with _stream(client, token, model['model_id'], 'req-badtool-1',
                 tools=[{'name': 't', 'input_schema': {'required': 'oops'}}]
                 ) as response:
        response.read()
        assert response.status_code == 400
        assert response.json()['error']['code'] == 'invalid_tool_schema'


def test_model_allowlist_enforced(client):
    admin, user = _admin_and_user(client)
    _setup_billable(client, admin, user)
    token = str(user['access_token'])
    with _stream(client, token, 'no-such-model', 'req-nomodel-1') as response:
        response.read()
        assert response.status_code == 409
        assert response.json()['error']['code'] == 'model_unavailable'


def test_messages_must_not_carry_file_paths_or_binary(client):
    admin, user = _admin_and_user(client)
    model = _setup_billable(client, admin, user)
    token = str(user['access_token'])
    # 平台约定：请求体结构校验失败统一 422 + invalid_request 信封，
    # 且不回显被拒绝的字段内容（防止泄露路径/密钥）。
    with _stream(client, token, model['model_id'], 'req-path-1',
                 messages=[{'role': 'user', 'content': '读这个',
                            'path': 'D:/secret.xlsx'}]) as response:
        response.read()
        assert response.status_code == 422
        assert response.json()['error']['code'] == 'invalid_request'
        assert 'secret.xlsx' not in response.text, '错误响应不得回显文件路径'
    with _stream(client, token, model['model_id'], 'req-bin-1',
                 messages=[{'role': 'user',
                            'content': {'base64': 'AAAA'}}]) as response:
        response.read()
        assert response.status_code == 422
        assert response.json()['error']['code'] == 'invalid_request'


def test_protocol_version_negotiation(client):
    admin, user = _admin_and_user(client)
    model = _setup_billable(client, admin, user)
    token = str(user['access_token'])
    with _stream(client, token, model['model_id'], 'req-proto-1',
                 protocol_version=99) as response:
        response.read()
        assert response.status_code == 400
        body = response.json()
        assert body['error']['code'] == 'unsupported_protocol_version'
        assert 1 in body['error']['supported_versions']


# ------------------------------------------------------------------ refresh 宽容窗口

def test_refresh_grace_keeps_concurrent_processes_alive(client):
    _admin, user = _admin_and_user(client)
    first = client.post('/api/v1/auth/refresh',
                        json={'refresh_token': user['refresh_token']})
    assert first.status_code == 200
    # 第二个进程仍持旧 refresh token：宽容窗口内必须可用，不得互相注销
    second = client.post('/api/v1/auth/refresh',
                         json={'refresh_token': user['refresh_token']})
    assert second.status_code == 200, '宽容窗口内旧 refresh token 必须可用'
    for tokens in (first.json(), second.json()):
        balance = client.get('/api/v1/account/balance',
                             headers=bearer(tokens['access_token']))
        assert balance.status_code == 200, '两个进程的新 access token 都必须有效'


def test_refresh_beyond_grace_rejected(client):
    _admin, user = _admin_and_user(client)
    first = client.post('/api/v1/auth/refresh',
                        json={'refresh_token': user['refresh_token']})
    assert first.status_code == 200
    with _db(client) as db:
        session = db.scalar(select(AuthSession).where(
            AuthSession.user_id == user['user']['user_id']))
        from datetime import timedelta

        from asset_based_agent.report_review_server.models import utc_now
        session.refresh_rotated_at = utc_now() - timedelta(seconds=3600)
        db.commit()
    stale = client.post('/api/v1/auth/refresh',
                        json={'refresh_token': user['refresh_token']})
    assert stale.status_code == 401, '超出宽容窗口的旧 refresh token 必须拒绝'


# ------------------------------------------------------------------ OpenAI SSE 解析

def test_openai_sse_parser_handles_text_toolcalls_and_usage():
    from asset_based_agent.report_review_server.services.provider_gateway import (
        iter_openai_stream_events,
    )
    lines = [
        'data: {"choices":[{"delta":{"role":"assistant"},"index":0}]}',
        '',
        'data: {"choices":[{"delta":{"content":"你"},"index":0}]}',
        '',
        'data: {"choices":[{"delta":{"content":"好"},"index":0}]}',
        '',
        ('data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"call_1",'
         '"function":{"name":"calc","arguments":""}}]},"index":0}]}'),
        '',
        ('data: {"choices":[{"delta":{"tool_calls":[{"index":0,'
         '"function":{"arguments":"{\\"x\\": 2}"}}]},"index":0}]}'),
        '',
        'data: {"choices":[{"delta":{},"finish_reason":"tool_calls","index":0}]}',
        '',
        ('data: {"usage":{"prompt_tokens":7,"completion_tokens":3,'
         '"total_tokens":10},"choices":[]}'),
        '',
        'data: [DONE]',
        '',
    ]
    events = list(iter_openai_stream_events(iter(lines)))
    kinds = [event['kind'] for event in events]
    assert kinds == ['message_start', 'text_delta', 'text_delta',
                     'tool_call_delta', 'tool_call_delta',
                     'tool_call_complete', 'usage', 'message_complete']
    assert events[2]['data'] == {'text': '好'}
    completed = events[5]['data']
    assert completed['name'] == 'calc'
    assert completed['arguments'] == {'x': 2}
    usage = events[6]['data']
    assert usage['input_tokens'] == 7 and usage['output_tokens'] == 3


# ------------------------------------------------------------------ sampling 保留键

def test_sampling_cannot_override_reserved_wire_keys(client):
    """sampling 只能携带采样参数，不得覆盖 messages/tools 等保留键。"""
    _admin, user = _admin_and_user(client)
    model = _setup_billable(client, _admin, user)
    service = AgentCompletionService(
        metered=client.app.state.review_job_service.metered,
        session_factory=client.app.state.session_factory)
    with _db(client) as db:
        prepared = service.begin(
            db, user_id=user['user']['user_id'], model_id=model['model_id'],
            client_request_id='req-sampling-1',
            messages=[{'role': 'user', 'content': '你好'}],
            tools=[{'name': 'calc', 'description': 'd',
                    'input_schema': {'type': 'object'}}],
            sampling={'temperature': 0.3,
                      'messages': [{'role': 'user', 'content': '劫持'}],
                      'tools': '劫持'})
    assert prepared.wire_payload['messages'] == [
        {'role': 'user', 'content': '你好'}]
    assert prepared.wire_payload['tools'][0]['function']['name'] == 'calc'
    assert prepared.wire_payload['temperature'] == 0.3
