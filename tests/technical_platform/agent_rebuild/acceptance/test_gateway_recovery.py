from asset_based_agent.technical_platform.agent_core.contracts import ModelEvent
from asset_based_agent.technical_platform.agent_core.fakes import FakeModelPort
from asset_based_agent.technical_platform.agent_gateway import AgentGateway
from asset_based_agent.technical_platform.flags import FeatureFlagStore
from asset_based_agent.technical_platform.store import PlatformStore


def _text_script(text):
    return [ModelEvent('message_start', {}),
            ModelEvent('text_delta', {'text': text}),
            ModelEvent('message_complete', {})]


def test_gateway_recovers_open_operation_before_new_submit(tmp_path):
    store = PlatformStore(tmp_path / 'db.sqlite', 'alice')
    project = store.create_project('one')
    session = store.create_session(project)
    flags = FeatureFlagStore(tmp_path / 'flags.json')
    flags.set_enabled('chat', True)
    models = iter([FakeModelPort([_text_script('新回复')])])
    gateway = AgentGateway(
        store, session, flags=flags,
        model_port_factory=lambda: next(models),
        permission_mode_getter=lambda: 'risk',
    )
    gateway._mirror_session()
    interrupted = gateway.repo.begin_operation(
        session, 'main', user_text='崩溃前消息', request_id='stale-operation')

    result = gateway.submit('恢复后消息')

    assert result['status'] == 'completed'
    assert gateway.repo.get_operation(interrupted.id).status == 'unknown'
    entries = gateway.repo.entries(session, 'main')
    assert any(entry.entry_type == 'error_message'
               and entry.operation_id == interrupted.id for entry in entries)
