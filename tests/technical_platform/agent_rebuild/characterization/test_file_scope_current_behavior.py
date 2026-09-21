"""S01 现状冻结：文件范围门禁（正确行为，重构全程必须保持）。"""
import pytest
from test_consultation_routing import SpyClient, add_file, consult_response, make_store


def test_consult_scope_is_exactly_current_selection(tmp_path):
    store, project, session = make_store(tmp_path)
    add_file(store, project, tmp_path, '旧文件.xlsx')
    second = add_file(store, project, tmp_path, '新文件.xlsx')
    spy = SpyClient()
    spy.understand_task = lambda payload, *, cancel=None: (
        spy.understand_calls.append(payload) or consult_response(payload))
    from asset_based_agent.technical_platform.turn_router import TurnRouter
    TurnRouter(store, spy).submit(session, '这个项目情况怎么样？', model_id='m', selected_ids=[second])
    sent = [f['id'] for f in spy.understand_calls[0]['files']]
    assert sent == [second], '历史文件不得混入本轮范围'


def test_router_rejects_foreign_or_duplicated_selection(tmp_path):
    store, project, session = make_store(tmp_path)
    file_id = add_file(store, project, tmp_path)
    from asset_based_agent.technical_platform.turn_router import TurnRouter
    router = TurnRouter(store, SpyClient())
    with pytest.raises(PermissionError):
        router.submit(session, '审核', model_id='m', selected_ids=['foreign'])
    with pytest.raises(PermissionError):
        router.submit(session, '审核', model_id='m', selected_ids=[file_id, file_id])


def test_envelope_verify_rejects_scope_and_mode_changes(tmp_path):
    from asset_based_agent.technical_platform.input_gateway import InputGateway
    store, project, session = make_store(tmp_path)
    file_id = add_file(store, project, tmp_path)
    gateway = InputGateway(store, lambda: 'full')
    envelope = gateway.create(session, '审核', selected_ids=[file_id], model_id='m')
    gateway.verify(envelope)
    drifted = InputGateway(store, lambda: 'request')
    with pytest.raises(PermissionError):
        drifted.verify(envelope)
