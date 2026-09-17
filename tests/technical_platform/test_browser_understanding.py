import json
from types import SimpleNamespace

import pytest

from asset_based_agent.agent_contracts import (
    TaskUnderstanding,
    UnderstandingRequest,
    validate_understanding,
)


def request_data(enabled=True):
    return {'request_id':'r', 'model_id':'m', 'message_id':'msg', 'prompt':'打开指定网站并查看公告',
            'skills': ([{'id':'browser.task', 'adapter':'browser.task', 'name':'浏览器任务',
                         'description':'本地浏览器；需要明确网站与动作范围'}] if enabled else [])}


def result_data():
    return {'message_intent':'execute', 'goal':'查看公告', 'targets':[], 'references':[], 'excluded':[],
            'constraints':[], 'deliverables':['公告摘要'], 'missing_inputs':[],
            'evidence_message_ids':['msg'], 'skill_ids':['browser.task'], 'next_action':'browser',
            'browser':{'origins':['https://example.com'], 'actions':['navigate','observe']},
            'reply':'准备查看该网站公告；执行前核对范围。'}


def test_browser_understanding_without_files_passes_server_and_client_policy():
    from asset_based_agent.report_review_server.services.task_understanding import (
        understand_task,
    )
    from asset_based_agent.technical_platform.understanding_policy import (
        assess_understanding,
    )
    request = UnderstandingRequest(**request_data())
    class Meter:
        def execute(self, *args, **kwargs):
            return SimpleNamespace(payload={'choices':[{'message':{'content':json.dumps(result_data())}}]})
    result = understand_task(Meter(), None, 'user', request)
    assert assess_understanding(request, result).next_action == 'browser'
    assert not result.targets and result.browser.origins == ['https://example.com']


@pytest.mark.parametrize('change', [
    {'targets':['file']}, {'skill_ids':['report.review']}, {'browser':None},
    {'browser':{'origins':['http://example.com'], 'actions':['observe']}},
    {'browser':{'origins':['https://example.com/path'], 'actions':['observe']}},
    {'browser':{'origins':['https://example.com'], 'actions':['eval']}},
    {'message_intent':'consult'},
])
def test_invalid_browser_decisions_are_rejected(change):
    with pytest.raises(ValueError):
        validate_understanding(UnderstandingRequest(**request_data()),
                               TaskUnderstanding(**{**result_data(), **change}))


def test_legacy_or_unavailable_client_cannot_receive_browser_execution():
    with pytest.raises(ValueError):
        validate_understanding(UnderstandingRequest(**request_data(False)), TaskUnderstanding(**result_data()))


def test_legacy_consultation_serialization_does_not_add_browser_fields():
    result = TaskUnderstanding(**{**result_data(), 'browser':None, 'message_intent':'consult',
                                'next_action':'answer', 'skill_ids':[]})
    assert 'browser' not in result.model_dump()
    assert 'browser' not in json.loads(result.model_dump_json())


def test_controller_only_advertises_browser_when_host_enables_it(tmp_path):
    from asset_based_agent.technical_platform.agent_controller import AgentController
    from asset_based_agent.technical_platform.store import PlatformStore
    store = PlatformStore(tmp_path/'db.sqlite', 'alice')
    session = store.create_session(store.create_project('one'))
    controller = AgentController(store)
    first = controller.prepare(session, '打开网站', model_id='m', selected_ids=[])
    assert all(s.id != 'browser.task' for s in first.request.skills)
    pending = controller.prepare(session, '打开网站', model_id='m', selected_ids=[], browser_enabled=True)
    data = {**result_data(), 'evidence_message_ids':[pending.request.message_id]}
    result = controller.complete(pending, data)
    assert result.next_action == 'browser'
    with store.connect() as db:
        assert db.execute('SELECT count(*) FROM runs').fetchone()[0] == 0


def test_external_candidates_cannot_enable_native_browser(tmp_path):
    from asset_based_agent.technical_platform.agent_controller import AgentController
    from asset_based_agent.technical_platform.store import PlatformStore
    store = PlatformStore(tmp_path/'db.sqlite', 'alice')
    session = store.create_session(store.create_project('one'))
    with pytest.raises(PermissionError):
        AgentController(store).prepare(session, '打开网站', model_id='m', selected_ids=[],
                                        candidates=request_data()['skills'])


def test_understood_browser_compiles_without_granting_permission(tmp_path):
    from asset_based_agent.technical_platform.browser_task_spec import (
        build_understood_browser_task,
    )
    from asset_based_agent.technical_platform.permissions import PermissionService
    from asset_based_agent.technical_platform.store import PlatformStore
    store = PlatformStore(tmp_path/'db.sqlite', 'alice')
    session = store.create_session(store.create_project('one'))
    request = UnderstandingRequest(**request_data())
    result = TaskUnderstanding(**result_data())
    snapshot = build_understood_browser_task(store, session, request, result, environment='test').to_snapshot()
    assert snapshot['browser_scope']['origins'] == result.browser.origins
    assert snapshot['user_request'] == request.prompt
    assert snapshot['understanding']['goal'] == result.goal
    assert snapshot['request_id'] == request.request_id
    assert snapshot['execution_plan']['identity']['request_id'] == request.request_id
    run = store.start_run(session, snapshot)
    with pytest.raises(PermissionError): PermissionService(store).verify(run)


def test_browser_goal_preserves_clarification_and_understood_limits(tmp_path):
    from asset_based_agent.technical_platform.browser_task_spec import (
        build_understood_browser_task,
    )
    from asset_based_agent.technical_platform.plan_confirmation import confirmation_text
    from asset_based_agent.technical_platform.store import PlatformStore
    store = PlatformStore(tmp_path/'db.sqlite', 'alice')
    session = store.create_session(store.create_project('one'))
    request = UnderstandingRequest(**{**request_data(), 'prompt':'The second one', 'context':[
        {'id':'original', 'role':'user', 'text':'Read announcements; never submit a form.'},
        {'id':'question', 'role':'assistant', 'text':'Which announcement?'}]})
    result = TaskUnderstanding(**{**result_data(), 'constraints':['Do not edit the website'],
                                'deliverables':['An English summary']})
    snapshot = build_understood_browser_task(store, session, request, result, environment='test').to_snapshot()
    goal = json.loads(snapshot['browser_goal'])
    assert goal['messages'] == [m.model_dump() for m in request.context] + [
        {'id':request.message_id, 'role':'user', 'text':request.prompt}]
    assert goal['goal'] == result.goal
    assert goal['constraints'] == result.constraints
    assert goal['deliverables'] == result.deliverables
    assert snapshot['browser_goal'] in confirmation_text(snapshot, tmp_path)


def test_browser_goal_limit_does_not_silently_drop_original_constraints(tmp_path):
    from asset_based_agent.technical_platform.browser_task_spec import (
        build_understood_browser_task,
    )
    from asset_based_agent.technical_platform.store import PlatformStore
    store = PlatformStore(tmp_path/'db.sqlite', 'alice')
    session = store.create_session(store.create_project('one'))
    request = UnderstandingRequest(**{**request_data(), 'context':[
        {'id':'original', 'role':'user', 'text':'x' * 12000}]})
    with pytest.raises(ValueError, match='浏览器任务上下文'):
        build_understood_browser_task(store, session, request,
                                      TaskUnderstanding(**result_data()), environment='test')
    assert store.runs(session) == []


def test_browser_execution_refuses_missing_clarified_goal():
    from asset_based_agent.technical_platform.browser_task_spec import (
        browser_execution_goal,
    )
    with pytest.raises(ValueError):
        browser_execution_goal({'user_request':'second', 'understanding':result_data()})
    assert browser_execution_goal({'user_request':'Inspect example.com'}) == 'Inspect example.com'
