# S15 接线子集：app 侧装配（ModelPort 工厂/批准桥/Worker）（先红后绿）。
import asyncio
from types import SimpleNamespace

import pytest

from asset_based_agent.technical_platform.agent_switch import (
    RISK_TO_OPERATION,
    ApproverBridge,
    client_model_port_factory,
)


class FakeClient:
    def __init__(self, token='tok-1'):
        self.base_url = 'https://server.example.com'
        self.access_token = token
        self.refresh_calls = 0

    def refresh(self):
        self.refresh_calls += 1
        self.access_token = f'tok-{self.refresh_calls + 1}'


def run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------- ModelPort 工厂

def test_factory_requires_connected_client():
    with pytest.raises(ValueError):
        client_model_port_factory(None)
    with pytest.raises(ValueError):
        client_model_port_factory(FakeClient(token=None))


def test_factory_builds_server_model_port():
    from asset_based_agent.technical_platform.model_port.server_model_port import (
        ServerModelPort,
    )
    factory = client_model_port_factory(FakeClient())
    port = factory()
    assert isinstance(port, ServerModelPort)
    assert port.base_url == 'https://server.example.com'
    assert port.token_manager.access_token == 'tok-1'


def test_token_refresh_bridges_sync_client():
    client = FakeClient()
    factory = client_model_port_factory(client)
    port = factory()
    refreshed = run(port.token_manager.refresh(stale_token='tok-1'))
    assert refreshed == 'tok-2'
    assert client.refresh_calls == 1


# ---------------------------------------------------------------- 批准桥

def test_every_tool_risk_maps_to_legacy_operation():
    from asset_based_agent.technical_platform.agent_core.contracts import (
        TOOL_RISKS,
    )
    from asset_based_agent.technical_platform.agent_permission_modes import (
        _OPERATIONS,
    )
    for risk in TOOL_RISKS:
        assert risk in RISK_TO_OPERATION, risk
        assert RISK_TO_OPERATION[risk] in _OPERATIONS, risk


def test_approver_bridge_calls_ask_fn_with_mapped_operation():
    from asset_based_agent.technical_platform.agent_core.contracts import (
        ToolDescriptor,
    )
    from asset_based_agent.technical_platform.policies.contracts import (
        ApprovalRequest,
        Principal,
    )
    calls = []

    def ask(operation, title, reason):
        calls.append((operation, title, reason))
        return True

    bridge = ApproverBridge(ask)
    request = ApprovalRequest(
        principal=Principal(session_id='s1', operation_id='o1'),
        mode='assisted',
        tool=ToolDescriptor(name='browser_upload', description='d',
                            input_schema={}, risk='external_upload'),
        arguments={}, reason='需要批准', grants=('upload',))
    assert run(bridge.approve(request)) is True
    assert calls and calls[0][0] == 'upload'
    assert 'browser_upload' in calls[0][1]


def test_approver_bridge_denial_passes_through():
    from asset_based_agent.technical_platform.agent_core.contracts import (
        ToolDescriptor,
    )
    from asset_based_agent.technical_platform.policies.contracts import (
        ApprovalRequest,
        Principal,
    )
    bridge = ApproverBridge(lambda operation, title, reason: False)
    request = ApprovalRequest(
        principal=Principal(session_id='s1', operation_id='o1'),
        mode='request',
        tool=ToolDescriptor(name='execute_skill_plan', description='d',
                            input_schema={}, risk='local_create'),
        arguments={}, reason='需要批准', grants=())
    assert run(bridge.approve(request)) is False


# ---------------------------------------------------------------- Worker（offscreen Qt）

def test_agent_turn_worker_streams_and_finishes(qapp=None):
    pytest.importorskip('PySide6')
    from PySide6.QtWidgets import QApplication

    from asset_based_agent.technical_platform.agent_switch import (
        AgentTurnWorker,
    )
    app = QApplication.instance() or QApplication([])

    class FakeGateway:
        def submit(self, text, *, on_event=None):
            if on_event is not None:
                on_event(SimpleNamespace(event_type='message_delta',
                                         payload={'text': '你'}))
                on_event(SimpleNamespace(event_type='message_delta',
                                         payload={'text': '好'}))
            return {'status': 'completed', 'reply': '你好', 'error_code': ''}

    worker = AgentTurnWorker(FakeGateway(), '你好')
    deltas, done = [], []
    worker.delta.connect(deltas.append)
    worker.done.connect(done.append)
    worker.start()
    assert worker.wait(10000)
    app.processEvents()
    assert deltas == ['你', '好']
    assert done == [{'status': 'completed', 'reply': '你好', 'error_code': ''}]
