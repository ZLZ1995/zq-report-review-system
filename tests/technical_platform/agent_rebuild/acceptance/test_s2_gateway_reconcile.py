"""S2-03 网关接线验收：submit 前对账 unknown operation（先红后绿）。"""
from asset_based_agent.technical_platform.agent_core.contracts import (
    ModelEvent,
)
from asset_based_agent.technical_platform.agent_core.fakes import (
    FakeModelPort,
)
from asset_based_agent.technical_platform.agent_gateway import AgentGateway
from asset_based_agent.technical_platform.flags import FeatureFlagStore
from asset_based_agent.technical_platform.store import PlatformStore


def text_script(text):
    return [ModelEvent('message_start', {}),
            ModelEvent('text_delta', {'text': text}),
            ModelEvent('message_complete', {})]


class ReconcilingFakeModelPort(FakeModelPort):
    """带对账能力的假 ModelPort：query/replay 由测试脚本控制。"""

    def __init__(self, scripts, *, reconcile_result=None, replay_events=()):
        super().__init__(scripts)
        self._reconcile_result = reconcile_result
        self._replay_events = list(replay_events)
        self.replay_calls = []

    def reconcile_request(self, client_request_id):
        if callable(self._reconcile_result):
            return self._reconcile_result(client_request_id)
        return self._reconcile_result

    def replay_request(self, client_request_id):
        self.replay_calls.append(client_request_id)
        return list(self._replay_events)


def test_gateway_reconciles_stale_operation_before_submit(tmp_path):
    store = PlatformStore(tmp_path / 'db.sqlite', 'alice')
    project = store.create_project('one')
    session = store.create_session(project)
    flags = FeatureFlagStore(tmp_path / 'flags.json')
    flags.set_enabled('chat', True)
    port = ReconcilingFakeModelPort(
        [text_script('新回答')],
        reconcile_result={'status': 'succeeded', 'billing_request_id': 'b1',
                          'replay_available': True, 'error_code': ''},
        replay_events=[{'kind': 'text_delta', 'data': {'text': '对账恢复文本'}},
                       {'kind': 'message_complete', 'data': {}}])
    gateway = AgentGateway(
        store, session, flags=flags, model_port_factory=lambda: port,
        permission_mode_getter=lambda: 'risk')
    gateway._mirror_session()
    stale = gateway.repo.begin_operation(session, 'main', user_text='旧请求',
                                         request_id='r-old')
    gateway.repo.begin_turn(stale.id, 1, input_context_sha256='x',
                            model_request_id='req-old')
    gateway.repo.interrupt_operation(stale.id, code='agent.interrupted',
                                     summary='进程中断')

    result = gateway.submit('新消息')
    assert result['status'] == 'completed'
    record = gateway.repo.get_operation(stale.id)
    assert record.status == 'completed', '服务端 succeeded 的 stale 轮必须 replay 收束'
    assert port.replay_calls == ['req-old']
    texts = [e.payload.get('text', '')
             for e in gateway.repo.entries(session, 'main')
             if e.entry_type == 'assistant_message']
    assert any('对账恢复文本' in t for t in texts)


def test_gateway_never_auto_replays_uncertain_operation(tmp_path):
    store = PlatformStore(tmp_path / 'db.sqlite', 'alice')
    project = store.create_project('one')
    session = store.create_session(project)
    flags = FeatureFlagStore(tmp_path / 'flags.json')
    flags.set_enabled('chat', True)
    port = ReconcilingFakeModelPort(
        [text_script('新回答')],
        reconcile_result={'status': 'uncertain', 'billing_request_id': 'b1',
                          'replay_available': False,
                          'error_code': 'provider_usage_missing'})
    gateway = AgentGateway(
        store, session, flags=flags, model_port_factory=lambda: port,
        permission_mode_getter=lambda: 'risk')
    gateway._mirror_session()
    stale = gateway.repo.begin_operation(session, 'main', user_text='旧请求',
                                         request_id='r-old')
    gateway.repo.begin_turn(stale.id, 1, input_context_sha256='x',
                            model_request_id='req-old')
    gateway.repo.interrupt_operation(stale.id, code='agent.interrupted',
                                     summary='进程中断')

    result = gateway.submit('新消息')
    assert result['status'] == 'completed'
    assert port.replay_calls == [], 'uncertain 绝不自动回放'
    assert gateway.repo.get_operation(stale.id).status == 'unknown'
