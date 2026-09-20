"""K01：用测试冻结“普通咨询被错误送入业务任务链”的当前故障。

修复前这些测试必须失败（turn_router 尚不存在 / 422 未分类 / 契约检查缺失）；
修复后全绿。间谍客户端只替代网络层，路由、裁决、状态机、存储全部走真实代码。
"""
import httpx
import pytest

from asset_based_agent.technical_platform.store import PlatformStore

# ------------------------------------------------------------------ helpers

def make_store(tmp_path):
    store = PlatformStore(tmp_path / 'db.sqlite', 'alice')
    project = store.create_project('one')
    session = store.create_session(project)
    return store, project, session


def add_file(store, project, tmp_path, name='资料.xlsx'):
    from openpyxl import Workbook

    from asset_based_agent.technical_platform.skills import digest
    path = tmp_path / name
    wb = Workbook()
    wb.active['A1'] = '合成表头'
    wb.save(path)
    wb.close()
    return store.add_file(project, path, digest(path))


def consult_response(request, text='审核默认只读，不修改原件。'):
    return {'schema_version': 1, 'message_intent': 'consult', 'goal': '',
            'targets': [], 'references': [], 'excluded': [], 'constraints': [],
            'deliverables': [], 'missing_inputs': [],
            'evidence_message_ids': [request['message_id']], 'skill_ids': [],
            'next_action': 'answer', 'reply': text}


class SpyClient:
    """记录理解调用并按脚本返回；任何其他客户端方法被调用即失败。"""

    def __init__(self, responses=()):
        self._responses = list(responses)
        self.understand_calls = []

    def understand_task(self, payload, *, cancel=None):
        self.understand_calls.append(payload)
        return self._responses.pop(0)

    def __getattr__(self, name):
        def forbidden(*args, **kwargs):
            raise AssertionError(f'咨询链路不得调用客户端方法: {name}')
        return forbidden


def load_router():
    from asset_based_agent.technical_platform.turn_router import TurnRouter
    return TurnRouter


def conversation_state(store, session):
    from asset_based_agent.technical_platform.conversation_state import (
        ConversationState,
    )
    return ConversationState(store).read(session)


# ------------------------------------------------------------------ K01-1

def test_social_greeting_answered_without_run_or_server_call(tmp_path):
    """项目中有已选文件时输入“你好”：普通回复、不创建任务、不发起联网理解。"""
    store, project, session = make_store(tmp_path)
    file_id = add_file(store, project, tmp_path)
    TurnRouter = load_router()
    spy = SpyClient()
    outcome = TurnRouter(store, spy).submit(
        session, '你好', model_id='m', selected_ids=[file_id])
    assert outcome.kind == 'answer'
    assert outcome.reply.strip()
    assert spy.understand_calls == []
    state = conversation_state(store, session)
    assert state['task_id'] is None and state['revision'] == 0
    assert [m['role'] for m in store.messages(session)] == ['user', 'assistant']


# ------------------------------------------------------------------ K01-2

def test_capability_consult_answered_with_empty_skills(tmp_path):
    """“你能帮我做什么”：返回咨询回答，skill_ids=[]，不进入能力规划。"""
    store, _project, session = make_store(tmp_path)
    TurnRouter = load_router()
    spy = SpyClient()
    # 先占位一个请求以取 message_id：间谍在调用时生成响应
    def respond(payload):
        return consult_response(payload, '我可以审核报告、生成评估明细表等。')
    spy.understand_task = lambda payload, *, cancel=None: (
        spy.understand_calls.append(payload) or respond(payload))
    outcome = TurnRouter(store, spy).submit(session, '你能帮我做什么', model_id='m', selected_ids=[])
    assert outcome.kind == 'answer'
    assert outcome.reply == '我可以帮你做这件事' or outcome.reply == '我可以审核报告、生成评估明细表等。'
    assert len(spy.understand_calls) == 1
    assert conversation_state(store, session)['task_id'] is None


# ------------------------------------------------------------------ K01-3

def test_general_knowledge_consult_not_planned(tmp_path):
    """一般评估知识问题：咨询回答，不进入 Skill 规划、不创建业务任务。"""
    store, _project, session = make_store(tmp_path)
    TurnRouter = load_router()
    spy = SpyClient()
    spy.understand_task = lambda payload, *, cancel=None: (
        spy.understand_calls.append(payload) or consult_response(payload, '通常包括声明、摘要、正文与附件。'))
    outcome = TurnRouter(store, spy).submit(
        session, '评估报告一般包括哪些部分？', model_id='m', selected_ids=[])
    assert outcome.kind == 'answer'
    assert '附件' in outcome.reply
    assert len(spy.understand_calls) == 1
    assert conversation_state(store, session)['task_id'] is None


# ------------------------------------------------------------------ K01-4

def test_consult_request_carries_no_material_evidence_or_file_content(tmp_path):
    """普通咨询的第一阶段请求不得携带 MaterialEvidence 或文件正文。"""
    store, project, session = make_store(tmp_path)
    file_id = add_file(store, project, tmp_path)
    TurnRouter = load_router()
    spy = SpyClient()
    spy.understand_task = lambda payload, *, cancel=None: (
        spy.understand_calls.append(payload) or consult_response(payload))
    outcome = TurnRouter(store, spy).submit(
        session, '审核报告时一般会看哪些问题？', model_id='m', selected_ids=[file_id])
    assert outcome.kind == 'answer'
    request = spy.understand_calls[0]
    assert len(request['files']) == 1
    sent = request['files'][0]
    assert set(sent) <= {'id', 'name', 'sha256'}, f'咨询请求夹带了扩展字段: {sorted(sent)}'
    assert '合成表头' not in str(request), '咨询请求不得包含文件正文'
    assert conversation_state(store, session)['task_id'] is None


# ------------------------------------------------------------------ K01-5

def test_old_server_strips_material_evidence_before_sending(tmp_path):
    """新客户端面对不支持 material_evidence 的旧服务端：剥离扩展字段后发送。"""
    from asset_based_agent.report_review_app.services.remote_auth_service import (
        MemoryCredentialStore,
        RemoteSessionClient,
    )
    posts = []

    def handler(request):
        if request.url.path.endswith('/capabilities'):
            return httpx.Response(200, json={
                'schema_version': 1, 'protocol_version': 1,
                'capabilities': {'task_understanding': 1}})
        if request.url.path.endswith('/agent/understand'):
            posts.append(request.content.decode('utf-8'))
            return httpx.Response(200, json={
                'schema_version': 1, 'message_intent': 'consult', 'goal': '',
                'targets': [], 'references': [], 'excluded': [], 'constraints': [],
                'deliverables': [], 'missing_inputs': [],
                'evidence_message_ids': ['q' * 32],
                'skill_ids': [], 'next_action': 'answer', 'reply': '好的。'})
        return httpx.Response(404)

    payload = {'request_id': 'r' * 32, 'model_id': 'm', 'message_id': 'q' * 32,
               'prompt': '审核这份报告', 'skills': [], 'context': [],
               'files': [{'id': 'f1', 'name': '报表.xlsx', 'sha256': 'a' * 64,
                          'evidence': {'format': 'xlsx', 'readable': True,
                                       'document_type': 'balance_sheet',
                                       'confidence': 0.98}}]}
    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        client = RemoteSessionClient('https://test.example/api/v1', client_instance_id='synthetic',
                                     credential_store=MemoryCredentialStore(), http_client=http)
        client.access_token = 'synthetic'
        result = client.understand_task(payload)
    assert result['next_action'] == 'answer'
    assert posts, '请求未发送到理解端点'
    assert '"evidence"' not in posts[0], '旧服务端不得收到 evidence 扩展字段'


# ------------------------------------------------------------------ K01-6

def test_server_422_unknown_field_is_request_schema_error_not_network():
    """旧服务端 422 拒绝未知字段：必须是请求 Schema 错误，不得显示为网络错误。"""
    from asset_based_agent.report_review_app.services.remote_auth_service import (
        MemoryCredentialStore,
        NetworkUnavailable,
        RemoteSessionClient,
        RequestSchemaError,
    )

    def handler(request):
        if request.url.path.endswith('/capabilities'):
            return httpx.Response(200, json={
                'schema_version': 1, 'protocol_version': 1,
                'capabilities': {'task_understanding': 1, 'material_evidence': 1}})
        if request.url.path.endswith('/agent/understand'):
            return httpx.Response(422, json={
                'detail': [{'loc': ['body', 'files', 0, 'evidence'],
                            'msg': 'extra fields not permitted', 'type': 'extra_forbidden'}]})
        return httpx.Response(404)

    payload = {'request_id': 'r' * 32, 'model_id': 'm', 'message_id': 'q' * 32,
               'prompt': '审核这份报告', 'skills': [], 'context': [],
               'files': [{'id': 'f1', 'name': '报表.xlsx', 'sha256': 'a' * 64,
                          'evidence': {'format': 'xlsx', 'readable': True,
                                       'document_type': 'balance_sheet',
                                       'confidence': 0.9}}]}
    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        client = RemoteSessionClient('https://test.example/api/v1', client_instance_id='synthetic',
                                     credential_store=MemoryCredentialStore(), http_client=http)
        client.access_token = 'synthetic'
        with pytest.raises(RequestSchemaError) as caught:
            client.understand_task(payload)
    assert not isinstance(caught.value, NetworkUnavailable)
    assert '网络' not in str(caught.value)


# ------------------------------------------------------------------ K01-7

def test_capability_openapi_mismatch_fails_contract_check():
    """服务端能力声明与 OpenAPI Schema 不一致时，发布前契约检查必须失败。"""
    from asset_based_agent.report_review_server.contract_check import (
        check_capabilities_against_openapi,
    )
    capabilities = {'schema_version': 1, 'protocol_version': 1,
                    'capabilities': {'task_understanding': 1, 'material_evidence': 1}}
    openapi_missing = {'components': {'schemas': {'EvidenceRef': {
        'type': 'object', 'additionalProperties': False,
        'properties': {'id': {'type': 'string'}, 'name': {'type': 'string'},
                       'sha256': {'type': 'string'}}}}}}
    issues = check_capabilities_against_openapi(capabilities, openapi_missing)
    assert issues, '声明 material_evidence 但 OpenAPI 缺 MaterialEvidence 时必须报错'
    assert any('material_evidence' in issue or 'MaterialEvidence' in issue for issue in issues)


# ------------------------------------------------------------------ K01-8

def test_consult_preserves_pending_clarification(tmp_path):
    """待澄清任务存在时提出独立咨询：回答咨询，pending 任务保留不动。"""
    from asset_based_agent.technical_platform.agent_controller import AgentController
    store, _project, session = make_store(tmp_path)
    controller = AgentController(store)
    first = controller.prepare(session, '帮我处理资料', model_id='m', selected_ids=[])
    ask = {'schema_version': 1, 'message_intent': 'clarify', 'goal': '',
           'targets': [], 'references': [], 'excluded': [], 'constraints': [],
           'deliverables': [], 'missing_inputs': [{'field': 'goal', 'question': '要审核还是生成？'}],
           'evidence_message_ids': [first.request.message_id], 'skill_ids': [],
           'next_action': 'ask', 'reply': '要审核还是生成？'}
    controller.complete(first, ask)
    before = conversation_state(store, session)
    assert before['question'] and before['task_id']

    TurnRouter = load_router()
    spy = SpyClient()
    spy.understand_task = lambda payload, *, cancel=None: (
        spy.understand_calls.append(payload) or consult_response(payload, '这样使用该功能。'))
    outcome = TurnRouter(store, spy).submit(session, '这个功能怎么用', model_id='m', selected_ids=[])
    assert outcome.kind == 'answer'
    after = conversation_state(store, session)
    assert after['question'] == before['question'], '咨询不得覆盖待澄清问题'
    assert after['task_id'] == before['task_id'] and after['revision'] == before['revision']


# ------------------------------------------------------------------ K01-9

def test_consult_creates_no_task_no_attachment_change_no_billing(tmp_path):
    """咨询不改变附件选择、不创建任务 ID、不触发余额/计划等付费链路。"""
    store, project, session = make_store(tmp_path)
    file_id = add_file(store, project, tmp_path)
    files_before = store.files(project)
    TurnRouter = load_router()
    spy = SpyClient()
    spy.understand_task = lambda payload, *, cancel=None: (
        spy.understand_calls.append(payload) or consult_response(payload))
    outcome = TurnRouter(store, spy).submit(
        session, '谢谢，顺便问下审核要多久', model_id='m', selected_ids=[file_id])
    assert outcome.kind == 'answer'
    assert conversation_state(store, session)['task_id'] is None
    assert store.files(project) == files_before
    assert len(spy.understand_calls) == 1, '咨询只允许一次轻量理解调用'


# ------------------------------------------------------------------ K04/K07

def consult_worker(store, session, client, prompt='最近的评估政策有什么变化', **kwargs):
    from asset_based_agent.technical_platform.routing import ConsultWorker
    worker = ConsultWorker(client, store, session, prompt,
                           model_id='m', selected_ids=[], **kwargs)
    worker.run()
    return worker


def test_consult_worker_answer_outcome_and_no_run(tmp_path):
    """阶段 1 判为咨询：TurnOutcome.answer 落消息，不创建任何任务。"""
    store, _project, session = make_store(tmp_path)
    client = SpyClient([consult_response(
        {'message_id': 'will-be-replaced'}, '评估基准日由委托合同约定。')])
    # SpyClient 返回前会用真实 payload 的 message_id 校验；直接取调用时的值
    original = client.understand_task
    def understand(payload, *, cancel=None):
        client._responses[0] = consult_response(payload, '评估基准日由委托合同约定。')
        return original(payload, cancel=cancel)
    client.understand_task = understand
    worker = consult_worker(store, session, client)
    assert worker.error is None
    assert worker.outcome.kind == 'answer'
    assert '评估基准日' in worker.outcome.reply
    assert conversation_state(store, session)['task_id'] is None


def test_consult_worker_network_failure_never_blames_skill(tmp_path):
    from asset_based_agent.report_review_app.services.remote_auth_service import (
        NetworkUnavailable,
    )
    store, _project, session = make_store(tmp_path)
    class Client:
        def understand_task(self, payload, *, cancel=None):
            raise NetworkUnavailable('connection refused')
    worker = consult_worker(store, session, Client())
    assert worker.outcome is None
    assert '网络' in worker.error
    assert 'Skill' not in worker.error


def test_consult_worker_session_revoked_and_balance_are_distinct(tmp_path):
    from asset_based_agent.report_review_app.services.remote_auth_service import (
        InsufficientBalance,
        SessionRevoked,
    )
    store, _project, session = make_store(tmp_path)
    class Revoked:
        def understand_task(self, payload, *, cancel=None):
            raise SessionRevoked('token expired')
    worker = consult_worker(store, session, Revoked())
    assert '登录会话已失效' in worker.error
    class Balance:
        def understand_task(self, payload, *, cancel=None):
            raise InsufficientBalance('账户余额不足，请先充值')
    worker = consult_worker(store, session, Balance())
    assert '余额不足' in worker.error
    assert '网络' not in worker.error and 'Skill' not in worker.error


def test_consult_worker_schema_error_keeps_version_compat_wording(tmp_path):
    from asset_based_agent.report_review_app.services.remote_auth_service import (
        RequestSchemaError,
    )
    store, _project, session = make_store(tmp_path)
    class Old422:
        def understand_task(self, payload, *, cancel=None):
            raise RequestSchemaError(
                '服务端无法识别本轮理解请求；客户端与服务端版本可能不兼容，请更新客户端或服务端。',
                error_code='http_422', http_status=422)
    worker = consult_worker(store, session, Old422())
    assert '不兼容' in worker.error
    assert 'Skill' not in worker.error


def test_consult_worker_cancel_stops_before_reply(tmp_path):
    store, _project, session = make_store(tmp_path)
    client = SpyClient()
    from asset_based_agent.technical_platform.routing import ConsultWorker
    worker = ConsultWorker(client, store, session, '你好，讲个笑话',
                           model_id='m', selected_ids=[])
    worker.cancel.set()
    worker.run()
    assert worker.outcome is None
    assert '取消' in worker.error
    assert client.understand_calls == []


# ------------------------------------------------------------------ K07

def make_remote_client(handler):
    from asset_based_agent.report_review_app.services.remote_auth_service import (
        MemoryCredentialStore,
        RemoteSessionClient,
    )
    http = httpx.Client(transport=httpx.MockTransport(handler))
    client = RemoteSessionClient('https://test.example/api/v1', client_instance_id='synthetic',
                                 credential_store=MemoryCredentialStore(), http_client=http)
    client.access_token = 'synthetic'
    return client


UNDERSTAND_PAYLOAD = {'request_id': 'r' * 32, 'model_id': 'm', 'message_id': 'q' * 32,
                      'prompt': '审核这份报告', 'skills': [], 'context': [],
                      'files': [{'id': 'f1', 'name': '报表.xlsx', 'sha256': 'a' * 64}]}


def capabilities_200():
    return httpx.Response(200, json={
        'schema_version': 1, 'protocol_version': 1,
        'capabilities': {'task_understanding': 1, 'material_evidence': 1}})


def test_model_provider_failure_maps_to_distinct_class():
    """服务端 all_providers_failed：必须是 model_provider_error，不得落入笼统错误。"""
    from asset_based_agent.report_review_app.services.remote_auth_service import (
        ModelProviderError,
        RemoteAuthenticationError,
        RequestSchemaError,
    )
    def handler(request):
        if request.url.path.endswith('/capabilities'):
            return capabilities_200()
        if request.url.path.endswith('/agent/understand'):
            return httpx.Response(502, json={'error': {
                'code': 'all_providers_failed', 'message': '所有模型渠道均调用失败。'}})
        return httpx.Response(404)
    client = make_remote_client(handler)
    with pytest.raises(ModelProviderError) as caught:
        client.understand_task(dict(UNDERSTAND_PAYLOAD))
    assert isinstance(caught.value, RemoteAuthenticationError)
    assert not isinstance(caught.value, RequestSchemaError)
    assert caught.value.error_code == 'model_provider_error'
    assert '模型渠道' in str(caught.value)


def test_http_422_message_names_version_incompatibility():
    """422 文案必须明确指出客户端与服务端版本不兼容。"""
    from asset_based_agent.report_review_app.services.remote_auth_service import (
        RequestSchemaError,
    )
    def handler(request):
        if request.url.path.endswith('/capabilities'):
            return capabilities_200()
        if request.url.path.endswith('/agent/understand'):
            return httpx.Response(422, json={
                'detail': [{'loc': ['body', 'files', 0, 'evidence'],
                            'msg': 'extra fields not permitted', 'type': 'extra_forbidden'}]})
        return httpx.Response(404)
    client = make_remote_client(handler)
    with pytest.raises(RequestSchemaError) as caught:
        client.understand_task(dict(UNDERSTAND_PAYLOAD))
    assert '客户端与服务端版本不兼容，请更新客户端或服务端' in str(caught.value)
    assert '可能不兼容' not in str(caught.value)


def test_consult_worker_model_provider_error_is_distinct(tmp_path):
    from asset_based_agent.report_review_app.services.remote_auth_service import (
        ModelProviderError,
    )
    store, _project, session = make_store(tmp_path)
    class Client:
        def understand_task(self, payload, *, cancel=None):
            raise ModelProviderError('所有模型渠道均调用失败。')
    worker = consult_worker(store, session, Client())
    assert '模型渠道' in worker.error
    assert 'Skill' not in worker.error
    assert '网络' not in worker.error


def test_consult_failure_log_correlates_by_request_id(tmp_path, caplog):
    """同一故障：日志中的 request_id 必须等于发出的理解请求编号。"""
    import logging

    from asset_based_agent.report_review_app.services.remote_auth_service import (
        NetworkUnavailable,
    )
    store, _project, session = make_store(tmp_path)
    seen = {}
    class Client:
        def understand_task(self, payload, *, cancel=None):
            seen['request_id'] = payload['request_id']
            raise NetworkUnavailable('connection refused')
    with caplog.at_level(logging.ERROR, logger='asset_based_agent.diagnostics'):
        worker = consult_worker(store, session, Client())
    assert '网络' in worker.error
    assert 'connection refused' not in worker.error, 'UI 不得暴露传输细节'
    message = next(r.getMessage() for r in caplog.records
                   if r.getMessage().startswith('stage=consult'))
    assert f"request_id={seen['request_id']}" in message
    assert 'client_version=' in message
    assert 'server_build=' in message


# ------------------------------------------------------------------ K08 C01/C02

@pytest.mark.parametrize('phrase', ['你好', '谢谢', '谢谢啦', '早上好', '再见', '你是谁'])
def test_social_phrases_answered_locally_without_run(tmp_path, phrase):
    """社交短语矩阵：全部本地直接回复，不发起联网理解，不创建任何任务。"""
    store, _project, session = make_store(tmp_path)
    spy = SpyClient()
    outcome = load_router()(store, spy).submit(session, phrase, model_id='m', selected_ids=[])
    assert outcome.kind == 'answer'
    assert outcome.reply
    assert spy.understand_calls == []
    assert conversation_state(store, session)['task_id'] is None
