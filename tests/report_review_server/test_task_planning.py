from copy import deepcopy

import pytest

from .test_task_understanding import Meter, request_data, result_data


def payload():
    return {'request': request_data(), 'understanding': result_data()}


def proposal():
    return {'request_id': 'r', 'steps': [
        {'step_id': 'review', 'skill_id': 'report.review', 'goal': '只审核新报告',
         'inputs': [{'kind': 'file', 'ref': 'new', 'role': 'target'}], 'dependencies': []}]}


def test_plan_proposal_is_metered_and_bound_without_business_execution():
    from asset_based_agent.agent_contracts import PlanningRequest
    from asset_based_agent.report_review_server.services.task_planning import (
        propose_plan,
    )
    meter = Meter(proposal())
    result = propose_plan(meter, None, 'u', PlanningRequest.model_validate(payload()))
    assert result.steps[0].inputs[0].ref == 'new'
    assert meter.calls[0]['client_request_id'] == 'plan:r'
    assert meter.calls[0]['model_id'] == 'm'
    assert 'permissions' not in result.model_dump()
    assert 'tool' not in result.steps[0].model_dump()
    assert 'JSON Schema' in meter.calls[0]['payload']['messages'][0]['content']


@pytest.mark.parametrize('change', [
    lambda p: p.update(request_id='other'),
    lambda p: p['steps'][0]['inputs'][0].update(ref='old'),
    lambda p: p['steps'][0].update(dependencies=['review']),
    lambda p: p['steps'][0].update(tool='shell'),
    lambda p: p['steps'][0].update(skill_id='unknown'),
])
def test_plan_proposal_rejects_untrusted_scope_dependencies_and_tools(change):
    from asset_based_agent.agent_contracts import PlanningRequest
    from asset_based_agent.report_review_server.services.auth_service import (
        ServiceError,
    )
    from asset_based_agent.report_review_server.services.task_planning import (
        propose_plan,
    )
    value = deepcopy(proposal())
    change(value)
    with pytest.raises(ServiceError, match='计划'):
        propose_plan(Meter(value), None, 'u', PlanningRequest.model_validate(payload()))


def test_planning_endpoint_auth_and_validated_response(client, monkeypatch):
    from asset_based_agent.agent_contracts import PlanProposal
    from asset_based_agent.report_review_server import api
    assert client.post('/api/v1/agent/plan', json=payload()).status_code == 401
    assert client.get('/api/v1/capabilities').json()['capabilities']['task_planning'] == 1
    token = client.post('/api/v1/auth/login', json={
        'username': 'admin', 'password': 'AdminPassword123!', 'client_instance_id': 'test',
    }).json()['access_token']
    calls = []
    def fake(metered, db, user_id, request):
        calls.append(request.request.request_id)
        return PlanProposal.model_validate(proposal())
    monkeypatch.setattr(api, 'propose_plan', fake)
    headers = {'Authorization': 'Bearer ' + token}
    assert client.post('/api/v1/agent/plan', json=payload(), headers=headers).status_code == 200
    invalid = payload()
    invalid['understanding']['targets'] = ['unknown']
    assert client.post('/api/v1/agent/plan', json=invalid, headers=headers).status_code == 422
    assert calls == ['r']


def test_invalid_request_cannot_reach_meter_even_via_model_copy():
    from asset_based_agent.agent_contracts import PlanningRequest
    from asset_based_agent.report_review_server.services.task_planning import (
        propose_plan,
    )
    request = PlanningRequest.model_validate(payload())
    request = request.model_copy(update={'understanding': request.understanding.model_copy(
        update={'targets': ['outside']})})
    meter = Meter(proposal())
    with pytest.raises(ValueError):
        propose_plan(meter, None, 'u', request)
    assert not meter.calls


@pytest.mark.parametrize('change', [
    lambda p: p['steps'].append(deepcopy(p['steps'][0])),
    lambda p: p['steps'][0]['inputs'].append(deepcopy(p['steps'][0]['inputs'][0])),
    lambda p: p['steps'][0]['inputs'][0].update(role='reference'),
    lambda p: p['steps'][0]['inputs'][0].update(kind='step_output', ref='missing'),
])
def test_shared_plan_validator_rejects_ambiguous_inputs(change):
    from asset_based_agent.agent_contracts import (
        PlanningRequest,
        PlanProposal,
        validate_proposal,
    )
    value = proposal()
    change(value)
    with pytest.raises(ValueError):
        validate_proposal(PlanningRequest.model_validate(payload()), PlanProposal.model_validate(value))
