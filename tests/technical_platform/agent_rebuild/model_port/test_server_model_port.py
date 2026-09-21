"""S06 客户端：ServerModelPort——SSE 解析、协议版本、幂等键、余额预检、
refresh single-flight、取消关流、计费回执、错误归类。

验收锚点（计划书 S06）：
- access token 过期可恢复（401 → single-flight refresh → 重试一次）；
- 取消有关闭流的动作（服务端据此留下 disconnected 对账状态）；
- 客户端无供应商 API Key；
- 请求不包含原始文件路径和二进制。
"""
import asyncio
import inspect
import json

import httpx

from asset_based_agent.technical_platform.agent_core.cancellation import (
    CancelToken,
)
from asset_based_agent.technical_platform.agent_core.contracts import (
    ModelRequest,
    ToolDescriptor,
)
from asset_based_agent.technical_platform.agent_core.errors import (
    AgentCancelled,
    ModelAuthFailed,
    ModelBalanceInsufficient,
    ModelBillingReconciliation,
    ModelProtocolError,
    ModelTimeout,
    ServerCapabilityUnavailable,
)
from asset_based_agent.technical_platform.model_port import (
    ServerModelPort,
    TokenManager,
    entries_to_wire_messages,
    iter_sse_events,
)

BASE = 'https://server.test'
BALANCE_PATH = '/api/v1/account/balance'
STREAM_PATH = '/api/v1/agent/completions/stream'


def run(coro):
    return asyncio.run(coro)


def sse_body(events):
    return ''.join(
        f'event: {kind}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n'
        for kind, data in events)


GREEN_EVENTS = [
    ('message_start', {}),
    ('text_delta', {'text': '你'}),
    ('text_delta', {'text': '好'}),
    ('usage', {'input_tokens': 10, 'output_tokens': 5}),
    ('message_complete', {}),
    ('receipt', {'billing_request_id': 'br-1', 'charged_amount': '3.50000000',
                 'replayed': False}),
]


def make_request(**overrides):
    values = {
        'model_id': 'stream-model',
        'messages': ({'role': 'user_message', 'payload': {'text': '你好'}},),
        'request_id': 'req-1',
        'client_version': '0.3.0',
    }
    values.update(overrides)
    return ModelRequest(**values)


class FakeServer:
    """可编排的服务端：按路径与 token 返回罐装响应，记录所有请求。"""

    def __init__(self, *, balance='50.00000000', events=None,
                 valid_tokens=('tok-old',), stream_content=None):
        self.balance = balance
        self.events = GREEN_EVENTS if events is None else events
        self.valid_tokens = set(valid_tokens)
        self.stream_content = stream_content
        self.requests = []

    def handler(self, request):
        self.requests.append(request)
        token = request.headers.get('authorization', '').removeprefix('Bearer ')
        if token not in self.valid_tokens:
            return httpx.Response(401, json={
                'error': {'code': 'token_expired', 'message': '过期'}})
        if request.url.path == BALANCE_PATH:
            return httpx.Response(200, json={
                'balance': self.balance, 'currency': 'CNY'})
        if request.url.path == STREAM_PATH:
            if self.stream_content is not None:
                return httpx.Response(
                    200, headers={'content-type': 'text/event-stream'},
                    content=self.stream_content)
            return httpx.Response(
                200, headers={'content-type': 'text/event-stream'},
                content=sse_body(self.events).encode('utf-8'))
        return httpx.Response(404, json={'error': {'code': 'not_found'}})


def make_port(server, *, refresh_fn=None, **kwargs):
    refresh_fn = refresh_fn or _never_refresh
    manager = TokenManager(access_token='tok-old', refresh_fn=refresh_fn)
    client = httpx.AsyncClient(transport=httpx.MockTransport(server.handler))
    port = ServerModelPort(
        base_url=BASE, token_manager=manager, client=client, **kwargs)
    return port, manager


async def _never_refresh():
    raise AssertionError('不应触发 refresh')


def collect(port, request, cancel=None):
    async def gather():
        return [event async for event in port.stream(
            request, cancel or CancelToken())]
    return run(gather())


# ------------------------------------------------------------------ SSE 解析

def test_sse_parser_splits_events_and_multiline_data():
    async def scenario():
        async def lines():
            for line in [
                    'event: text_delta',
                    'data: {"text": "你',
                    'data: 好"}',
                    '',
                    'event: usage',
                    'data: {"input_tokens": 1}',
                    '',
                    '',
                    'event: message_complete',
                    'data: {}',
                    '']:
                yield line
        return [(kind, data) async for kind, data in iter_sse_events(lines())]
    events = run(scenario())
    assert events == [
        ('text_delta', {'text': '你好'}),
        ('usage', {'input_tokens': 1}),
        ('message_complete', {}),
    ]


def test_sse_parser_rejects_malformed_json():
    async def scenario():
        async def lines():
            yield 'event: text_delta'
            yield 'data: {oops'
            yield ''
        return [item async for item in iter_sse_events(lines())]
    try:
        run(scenario())
    except ModelProtocolError:
        return
    raise AssertionError('坏 JSON 必须归类为 ModelProtocolError')


# ------------------------------------------------------------------ 全绿链路

def test_full_green_stream_maps_events_and_folds_receipt():
    server = FakeServer()
    port, _manager = make_port(server)
    events = collect(port, make_request())
    kinds = [event.kind for event in events]
    assert kinds == ['message_start', 'text_delta', 'text_delta',
                     'message_complete', 'usage']
    usage = events[-1].data
    assert usage['input_tokens'] == 10 and usage['output_tokens'] == 5
    assert usage['charged_amount'] == '3.50000000'
    assert usage['billing_request_id'] == 'br-1'
    assert usage['replayed'] is False
    assert port.last_receipt['billing_request_id'] == 'br-1'

    stream_posts = [r for r in server.requests if r.url.path == STREAM_PATH]
    assert len(stream_posts) == 1
    payload = json.loads(stream_posts[0].content)
    assert payload['protocol_version'] == 1
    assert payload['client_request_id'] == 'req-1'
    assert payload['client_version'] == '0.3.0'
    assert payload['model_id'] == 'stream-model'
    assert payload['messages'] == [{'role': 'user', 'content': '你好'}]
    assert payload['tools'] == []


def test_replayed_receipt_is_marked_in_usage():
    events = [item for item in GREEN_EVENTS]
    events[-1] = ('receipt', {'billing_request_id': 'br-1',
                              'charged_amount': '3.50000000',
                              'replayed': True})
    server = FakeServer(events=events)
    port, _manager = make_port(server)
    result = collect(port, make_request())
    usage = result[-1].data
    assert usage['replayed'] is True


def test_tools_and_sampling_are_serialized_without_reserved_override():
    server = FakeServer()
    port, _manager = make_port(server)
    descriptor = ToolDescriptor(
        name='calc', description='计算',
        input_schema={'type': 'object',
                      'properties': {'x': {'type': 'number'}},
                      'required': ['x']})
    request = make_request(
        tools=(descriptor,),
        sampling={'temperature': 0.2,
                  'messages': [{'role': 'user', 'content': '劫持'}]})
    collect(port, request)
    payload = json.loads(
        next(r for r in server.requests
             if r.url.path == STREAM_PATH).content)
    assert payload['tools'] == [{
        'name': 'calc', 'description': '计算',
        'input_schema': descriptor.input_schema}]
    assert payload['sampling'] == {'temperature': 0.2}, \
        'sampling 不得携带 messages/tools 保留键'


# ------------------------------------------------------------------ 余额预检

def test_balance_preflight_blocks_insufficient_balance():
    server = FakeServer(balance='0.00000000')
    port, _manager = make_port(server)
    try:
        collect(port, make_request())
    except ModelBalanceInsufficient as exc:
        assert exc.code == 'model.balance_insufficient'
    else:
        raise AssertionError('余额不足必须阻止发起模型请求')
    assert not [r for r in server.requests if r.url.path == STREAM_PATH], \
        '余额不足时不得发起流式请求'


def test_balance_preflight_network_failure_is_advisory():
    """预检失败（网络）不阻断：服务端计费等稳态判断仍是权威。"""

    def handler(request):
        if request.url.path == BALANCE_PATH:
            raise httpx.ConnectError('boom', request=request)
        return FakeServer().handler(request)
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    port = ServerModelPort(
        base_url=BASE,
        token_manager=TokenManager(access_token='tok-old',
                                   refresh_fn=_never_refresh),
        client=client)
    events = collect(port, make_request())
    assert events[0].kind == 'message_start'


# ------------------------------------------------------------------ refresh 单飞

def test_401_triggers_single_flight_refresh_for_concurrent_streams():
    calls = []

    async def refresh():
        calls.append(1)
        await asyncio.sleep(0.05)  # 放大并发窗口
        return 'tok-new'

    server = FakeServer(valid_tokens=('tok-new',))
    port, manager = make_port(server, refresh_fn=refresh)

    async def scenario():
        return await asyncio.gather(
            _collect_async(port, make_request(request_id='req-a')),
            _collect_async(port, make_request(request_id='req-b')))

    first, second = run(scenario())
    assert calls == [1], '并发 401 只能触发一次真实 refresh'
    assert manager.access_token == 'tok-new'
    assert [e.kind for e in first][-1] == 'usage'
    assert [e.kind for e in second][-1] == 'usage'


async def _collect_async(port, request):
    return [event async for event in port.stream(request, CancelToken())]


def test_401_with_failed_refresh_maps_to_auth_error():
    async def refresh():
        raise ModelAuthFailed('登录已失效')

    server = FakeServer(valid_tokens=('someone-else',))
    port, _manager = make_port(server, refresh_fn=refresh)
    try:
        collect(port, make_request())
    except ModelAuthFailed:
        return
    raise AssertionError('refresh 失败必须归类为 ModelAuthFailed')


# ------------------------------------------------------------------ 取消

def test_cancellation_closes_stream_and_raises_cancelled():
    closed = asyncio.Event()

    async def slow_content():
        yield b'event: message_start\ndata: {}\n\n'
        try:
            await asyncio.sleep(30)
        finally:
            closed.set()

    server = FakeServer(stream_content=slow_content())
    port, _manager = make_port(server)
    cancel = CancelToken()

    async def scenario():
        async def cancel_soon():
            await asyncio.sleep(0.1)
            cancel.cancel()
        watcher = asyncio.ensure_future(cancel_soon())
        try:
            async for _event in port.stream(make_request(), cancel):
                pass
        finally:
            await watcher
    try:
        run(scenario())
    except AgentCancelled:
        pass
    else:
        raise AssertionError('取消必须以 AgentCancelled 收束')
    assert run(asyncio.wait_for(closed.wait(), timeout=2)), \
        '取消必须关闭底层 HTTP 流（服务端据此进入 disconnected 对账状态）'


# ------------------------------------------------------------------ 错误归类

def test_server_error_event_maps_to_stable_agent_error():
    events = [
        ('message_start', {}),
        ('error', {'code': 'provider_auth_failed', 'message': 'bad key'}),
    ]
    server = FakeServer(events=events)
    port, _manager = make_port(server)
    try:
        collect(port, make_request())
    except ModelAuthFailed as exc:
        assert exc.code == 'model.auth_failed'
    else:
        raise AssertionError('provider_auth_failed 必须归类为 ModelAuthFailed')


def test_billing_reconciliation_maps_from_status_and_event():
    envelope = httpx.Response(409, json={'error': {
        'code': 'billing_reconciliation_required', 'message': '对账'}})

    def handler(request):
        if request.url.path == BALANCE_PATH:
            return httpx.Response(200, json={'balance': '50', 'currency': 'CNY'})
        return envelope
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    port = ServerModelPort(
        base_url=BASE,
        token_manager=TokenManager(access_token='tok-old',
                                   refresh_fn=_never_refresh),
        client=client)
    try:
        collect(port, make_request())
    except ModelBillingReconciliation as exc:
        assert exc.code == 'model.billing_reconciliation'
    else:
        raise AssertionError('409 对账信号必须归类为 ModelBillingReconciliation')

    events = [('error', {'code': 'billing_reconciliation_required',
                         'message': '对账'})]
    server = FakeServer(events=events)
    port2, _manager2 = make_port(server)
    try:
        collect(port2, make_request())
    except ModelBillingReconciliation:
        return
    raise AssertionError('流内对账信号必须归类为 ModelBillingReconciliation')


def test_unsupported_protocol_version_maps_protocol_error():
    def handler(request):
        if request.url.path == BALANCE_PATH:
            return httpx.Response(200, json={'balance': '50', 'currency': 'CNY'})
        return httpx.Response(400, json={'error': {
            'code': 'unsupported_protocol_version', 'message': '升级',
            'supported_versions': [1]}})
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    port = ServerModelPort(
        base_url=BASE,
        token_manager=TokenManager(access_token='tok-old',
                                   refresh_fn=_never_refresh),
        client=client)
    try:
        collect(port, make_request(protocol_version=99))
    except ModelProtocolError:
        return
    raise AssertionError('协议版本拒绝必须归类为 ModelProtocolError')


def test_network_failure_maps_to_timeout():
    def handler(request):
        if request.url.path == BALANCE_PATH:
            return httpx.Response(200, json={'balance': '50', 'currency': 'CNY'})
        raise httpx.ConnectError('boom', request=request)
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    port = ServerModelPort(
        base_url=BASE,
        token_manager=TokenManager(access_token='tok-old',
                                   refresh_fn=_never_refresh),
        client=client)
    try:
        collect(port, make_request())
    except ModelTimeout:
        return
    raise AssertionError('网络失败必须归类为 ModelTimeout')


def test_required_stream_capability_blocks_before_model_request():
    requests = []

    def handler(request):
        requests.append(request.url.path)
        if request.url.path == BALANCE_PATH:
            return httpx.Response(200, json={'balance': '50', 'currency': 'CNY'})
        if request.url.path == '/api/v1/capabilities':
            return httpx.Response(200, json={
                'schema_version': 1, 'protocol_version': 1,
                'capabilities': {}})
        raise AssertionError('能力不足时不得打开流式模型请求')

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    port = ServerModelPort(
        base_url=BASE,
        token_manager=TokenManager(access_token='tok-old',
                                   refresh_fn=_never_refresh),
        client=client, require_stream_capability=True)
    try:
        collect(port, make_request())
    except ServerCapabilityUnavailable as exc:
        assert exc.code == 'server.capability_missing'
    else:
        raise AssertionError('缺少流式能力必须在模型请求前阻断')
    assert '/api/v1/agent/completions/stream' not in requests
    assert requests[-1] == '/api/v1/capabilities'


def test_versioned_base_url_does_not_duplicate_api_prefix():
    """The production auth client passes a base URL ending in /api/v1."""
    requests = []

    def handler(request):
        requests.append(request.url.path)
        if request.url.path == BALANCE_PATH:
            return httpx.Response(200, json={'balance': '50', 'currency': 'CNY'})
        if request.url.path == '/api/v1/capabilities':
            return httpx.Response(200, json={
                'schema_version': 1, 'protocol_version': 1,
                'capabilities': {'agent_completion_stream': 1}})
        if request.url.path == STREAM_PATH:
            return httpx.Response(
                200, headers={'content-type': 'text/event-stream'},
                content=sse_body(GREEN_EVENTS).encode('utf-8'))
        return httpx.Response(404)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    port = ServerModelPort(
        base_url=BASE + '/api/v1',
        token_manager=TokenManager(access_token='tok-old',
                                   refresh_fn=_never_refresh),
        client=client, require_stream_capability=True)
    events = collect(port, make_request())
    assert any(event.kind == 'message_complete' for event in events)
    assert '/api/v1/api/v1/capabilities' not in requests
    assert '/api/v1/api/v1/agent/completions/stream' not in requests


# ------------------------------------------------------------------ 消息映射

def test_entries_to_wire_messages_flattens_all_entry_types():
    entries = [
        {'role': 'user_message', 'payload': {'text': '第一问'}},
        {'role': 'assistant_message', 'payload': {'text': '第一答'}},
        {'role': 'tool_call', 'payload': {
            'id': 'c1', 'name': 'calc', 'arguments': {'x': 2}}},
        {'role': 'tool_result', 'payload': {
            'tool_call_id': 'c1', 'name': 'calc', 'status': 'succeeded',
            'result': 4, 'content': '4', 'error_code': ''}},
        {'role': 'system_note', 'payload': {'text': '注意'}},
        {'role': 'context_summary', 'payload': {'text': '前文摘要'}},
        {'role': 'artifact_reference', 'payload': {'summary': '报表.xlsx'}},
        {'role': 'error_message', 'payload': {'text': '失败', 'error_code': 'x'}},
        {'role': 'user_message', 'payload': {'text': '   '}},
    ]
    wire = entries_to_wire_messages(entries)
    assert wire == [
        {'role': 'user', 'content': '第一问'},
        {'role': 'assistant', 'content': '第一答'},
        {'role': 'assistant',
         'content': '[工具调用] calc: {"x": 2}'},
        {'role': 'user', 'content': '[工具结果] calc: 4'},
        {'role': 'system', 'content': '注意'},
        {'role': 'system', 'content': '[上下文摘要] 前文摘要'},
        {'role': 'user', 'content': '[产物引用] 报表.xlsx'},
    ], 'error_message 与空白消息必须被丢弃，tool 历史必须文本化'


# ------------------------------------------------------------------ 安全验收

FORBIDDEN_KEY_FRAGMENTS = (
    'path', 'base64', 'binary', 'blob', 'bytes', 'api_key', 'secret')


def _walk_keys(node):
    if isinstance(node, dict):
        for key, value in node.items():
            yield str(key)
            yield from _walk_keys(value)
    elif isinstance(node, list):
        for item in node:
            yield from _walk_keys(item)


def test_request_payload_carries_no_paths_or_binary():
    server = FakeServer()
    port, _manager = make_port(server)
    descriptor = ToolDescriptor(
        name='read', description='读取', input_schema={'type': 'object'})
    collect(port, make_request(
        messages=(
            {'role': 'user_message',
             'payload': {'text': '分析 D:/data/报表.xlsx'}},
        ),
        tools=(descriptor,)))
    payload = json.loads(
        next(r for r in server.requests
             if r.url.path == STREAM_PATH).content)
    for key in _walk_keys(payload):
        lowered = key.lower()
        assert not any(fragment in lowered
                       for fragment in FORBIDDEN_KEY_FRAGMENTS), \
            f'请求负载不得包含路径/二进制/密钥类字段: {key}'
    # 文件内容只能以用户可见文本形式出现，不存在结构化路径/二进制字段
    assert payload['messages'][0]['content'] == '分析 D:/data/报表.xlsx'


def test_client_configuration_has_no_provider_api_key():
    parameters = set(inspect.signature(ServerModelPort.__init__).parameters)
    for name in parameters:
        lowered = name.lower()
        assert 'api_key' not in lowered and 'secret' not in lowered, \
            f'客户端配置不得持有供应商密钥: {name}'
    server = FakeServer()
    port, _manager = make_port(server)
    collect(port, make_request())
    for request in server.requests:
        body = request.content.decode('utf-8')
        assert 'api_key' not in body and 'sk-' not in body, \
            '任何出站请求都不得携带供应商密钥'
