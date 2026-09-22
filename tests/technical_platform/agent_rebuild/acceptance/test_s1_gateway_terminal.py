"""S1 网关侧验收：统一 operation_id + unknown operation 清理（先红后绿）。"""
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


def make_stack(tmp_path, *, flags_on=('chat',), scripts=()):
    store = PlatformStore(tmp_path / 'db.sqlite', 'alice')
    project = store.create_project('one')
    session = store.create_session(project)
    flags = FeatureFlagStore(tmp_path / 'flags.json')
    for category in flags_on:
        flags.set_enabled(category, True)
    models = iter(FakeModelPort(list(group)) for group in scripts)
    gateway = AgentGateway(
        store, session, flags=flags,
        model_port_factory=lambda: next(models),
        permission_mode_getter=lambda: 'risk',
    )
    return store, session, gateway


def test_ui_operation_id_matches_repo_operation_id(tmp_path):
    _, session, gateway = make_stack(tmp_path, scripts=[[text_script('你好！')]])
    result = gateway.submit('你好')
    assert result['status'] == 'completed'
    operation_id = result.get('operation_id')
    assert operation_id, 'submit 结果必须携带真实 durable operation_id'
    record = gateway.repo.get_operation(operation_id)
    assert record.session_id == session
    assert record.status == 'completed'


def test_gateway_submit_returns_operation_id_on_failure(tmp_path):
    from asset_based_agent.technical_platform.agent_core.errors import (
        ModelTimeout,
    )
    _, _session, gateway = make_stack(tmp_path, scripts=[[ModelTimeout('超时')]])
    result = gateway.submit('你好')
    assert result['status'] == 'failed'
    operation_id = result.get('operation_id')
    assert operation_id, '失败路径同样必须携带 operation_id 供 UI 对账'
    record = gateway.repo.get_operation(operation_id)
    assert record.status == 'failed'


def test_unknown_operation_removed_from_gateway_open_set(tmp_path):
    _, session, gateway = make_stack(tmp_path, scripts=[[text_script('好')]])
    gateway._mirror_session()
    stale = gateway.repo.begin_operation(session, 'main', user_text='残留',
                                         request_id='r-stale')
    result = gateway.submit('你好')
    assert result['status'] == 'completed'
    assert gateway.repo.get_operation(stale.id).status == 'unknown'
    assert gateway._open_operations == set(), \
        'operation_unknown 后不得残留在 gateway open 集合'
