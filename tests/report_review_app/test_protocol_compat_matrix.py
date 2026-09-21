"""K02：客户端—服务端协议兼容矩阵。

矩阵行：基础+基础、新+旧、新+新、能力声明造假、OpenAPI 缺字段、
422/401/402/5xx 错误分类。所有请求在 MockTransport 或本地 TestClient 上
走真实 RemoteSessionClient / FastAPI 应用，不 mock 业务逻辑。
"""
import httpx
import pytest

from asset_based_agent.report_review_app.services.remote_auth_service import (
    InsufficientBalance,
    MemoryCredentialStore,
    RemoteAuthenticationError,
    RemoteSessionClient,
    RequestSchemaError,
    ServerCapabilityUnavailable,
    SessionRevoked,
)

UNDERSTAND_OK = {'schema_version': 1, 'message_intent': 'consult', 'goal': '',
                 'targets': [], 'references': [], 'excluded': [], 'constraints': [],
                 'deliverables': [], 'missing_inputs': [],
                 'evidence_message_ids': ['q' * 32], 'skill_ids': [],
                 'next_action': 'answer', 'reply': '好的。'}

EVIDENCE = {'format': 'xlsx', 'readable': True, 'document_type': 'balance_sheet',
            'confidence': 0.98}


def understand_payload(*, with_evidence):
    files = [{'id': 'f1', 'name': '报表.xlsx', 'sha256': 'a' * 64}]
    if with_evidence:
        files[0]['evidence'] = dict(EVIDENCE)
    return {'request_id': 'r' * 32, 'model_id': 'm', 'message_id': 'q' * 32,
            'prompt': '审核这份报告', 'skills': [], 'context': [], 'files': files}


def make_client(handler):
    http = httpx.Client(transport=httpx.MockTransport(handler))
    client = RemoteSessionClient('https://test.example/api/v1', client_instance_id='synthetic',
                                 credential_store=MemoryCredentialStore(), http_client=http)
    client.access_token = 'synthetic'
    return client


def capabilities_doc(**caps):
    return {'schema_version': 1, 'protocol_version': 1, 'capabilities': caps}


# ------------------------------------------------------- 基础客户端 + 基础服务端

def test_basic_client_against_basic_server():
    posts = []

    def handler(request):
        if request.url.path.endswith('/capabilities'):
            return httpx.Response(200, json=capabilities_doc(task_understanding=1))
        posts.append(request.content.decode('utf-8'))
        return httpx.Response(200, json=UNDERSTAND_OK)

    result = make_client(handler).understand_task(understand_payload(with_evidence=False))
    assert result['next_action'] == 'answer'
    assert '"evidence"' not in posts[0]


# ------------------------------------------------------- 新客户端 + 旧服务端

def test_new_client_against_legacy_server_degrades_and_revalidates():
    posts = []

    def handler(request):
        if request.url.path.endswith('/capabilities'):
            return httpx.Response(200, json=capabilities_doc(task_understanding=1))
        posts.append(request.content.decode('utf-8'))
        return httpx.Response(200, json=UNDERSTAND_OK)

    result = make_client(handler).understand_task(understand_payload(with_evidence=True))
    assert result['next_action'] == 'answer'
    assert posts and '"evidence"' not in posts[0], '降级后请求必须删除 evidence 字段'
    assert '"f1"' in posts[0] and '报表.xlsx' in posts[0], '降级只删扩展字段，保留文件身份'


# ------------------------------------------------------- 新客户端 + 新服务端

def test_new_client_against_new_server_keeps_material_evidence():
    posts = []

    def handler(request):
        if request.url.path.endswith('/capabilities'):
            return httpx.Response(200, json=capabilities_doc(
                task_understanding=1, material_evidence=1))
        posts.append(request.content.decode('utf-8'))
        return httpx.Response(200, json=UNDERSTAND_OK)

    result = make_client(handler).understand_task(understand_payload(with_evidence=True))
    assert result['next_action'] == 'answer'
    assert '"evidence"' in posts[0] and 'balance_sheet' in posts[0]


# ------------------------------------------------------- 能力声明造假

def test_server_advertises_capability_but_rejects_field_fails_closed():
    def handler(request):
        if request.url.path.endswith('/capabilities'):
            return httpx.Response(200, json=capabilities_doc(
                task_understanding=1, material_evidence=1))
        return httpx.Response(422, json={'detail': [
            {'loc': ['body', 'files', 0, 'evidence'], 'msg': 'extra fields not permitted',
             'type': 'extra_forbidden'}]})

    with pytest.raises(RequestSchemaError) as caught:
        make_client(handler).understand_task(understand_payload(with_evidence=True))
    assert '不兼容' in str(caught.value)
    assert caught.value.http_status == 422


# ------------------------------------------------------- OpenAPI 缺字段（legacy 探测）

def test_legacy_probe_openapi_missing_endpoint_is_capability_unavailable():
    def handler(request):
        if request.url.path.endswith('/capabilities'):
            return httpx.Response(404)
        if request.url.path.endswith('/openapi.json'):
            return httpx.Response(200, json={'paths': {}})
        return httpx.Response(404)

    with pytest.raises(ServerCapabilityUnavailable):
        make_client(handler).understand_task(understand_payload(with_evidence=False))


# ------------------------------------------------------- 401 / 402 / 5xx 分类

def test_401_session_revoked_is_not_network_error():
    def handler(request):
        if request.url.path.endswith('/capabilities'):
            return httpx.Response(200, json=capabilities_doc(task_understanding=1))
        return httpx.Response(401, json={'error': {'code': 'session_revoked',
                                                   'message': '会话已在别处登录'}})

    with pytest.raises(SessionRevoked):
        make_client(handler).understand_task(understand_payload(with_evidence=False))


def test_402_insufficient_balance_blocks_before_execution():
    def handler(request):
        if request.url.path.endswith('/capabilities'):
            return httpx.Response(200, json=capabilities_doc(task_understanding=1))
        return httpx.Response(402, json={'error': {'code': 'insufficient_balance',
                                                   'message': '余额不足'}})

    with pytest.raises(InsufficientBalance):
        make_client(handler).understand_task(understand_payload(with_evidence=False))


def test_5xx_keeps_distinct_http_code():
    def handler(request):
        if request.url.path.endswith('/capabilities'):
            return httpx.Response(200, json=capabilities_doc(task_understanding=1))
        return httpx.Response(503, json={'error': {'code': 'http_error', 'message': '网关错误'}})

    with pytest.raises(RemoteAuthenticationError) as caught:
        make_client(handler).understand_task(understand_payload(with_evidence=False))
    assert caught.value.http_status == 503
    assert not isinstance(caught.value, RequestSchemaError)
