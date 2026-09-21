import json
from types import SimpleNamespace

import pytest


def request_data():
    return {'request_id':'r', 'model_id':'m', 'task_id':'task', 'sequence':1,
            'goal':'Read the project information',
            'scope':{'origins':['https://example.com'], 'actions':['observe','click','fill','select','navigate']},
            'observation':{'nonce':'n', 'page_version':1, 'origin':'https://example.com',
                'text':'Project alpha exists', 'truncated':False, 'untrusted':True,
                'controls':[{'id':'1', 'kind':'button', 'text':'Open project', 'disabled':False}]}}


def proposal(**changes):
    return {'request_id':'r', 'action':'click', 'target':'1', 'value':'', 'url':'',
            'summary':'Open the specified project', 'evidence':'', **changes}


def test_browser_step_reuses_meter_and_validates_observed_target():
    from asset_based_agent.browser_contracts import BrowserStepRequest
    from asset_based_agent.report_review_server.services.browser_step import (
        propose_browser_step,
    )
    calls = []
    class Meter:
        def execute(self, db, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(payload={'choices':[{'message':{'content':json.dumps(proposal())}}]})
    result = propose_browser_step(Meter(), None, 'user', BrowserStepRequest(**request_data()))
    assert result.target == '1'
    assert calls[0]['client_request_id'] == 'browser:r'
    assert calls[0]['user_id'] == 'user'
    assert calls[0]['payload']['response_format'] == {'type':'json_object'}


@pytest.mark.parametrize('changes', [
    {'target':'invented'}, {'action':'eval'}, {'request_id':'other'},
    {'action':'fill','value':'x'}, {'url':'https://evil.example'},
    {'action':'navigate','target':'','url':'https://evil.example'},
    {'action':'finish','target':'','evidence':'invented receipt'},
    {'password':'secret'},
])
def test_browser_proposal_rejects_unobserved_or_out_of_scope_actions(changes):
    from asset_based_agent.browser_contracts import (
        BrowserStepProposal,
        BrowserStepRequest,
        validate_browser_step,
    )
    with pytest.raises(ValueError):
        validate_browser_step(BrowserStepRequest(**request_data()), BrowserStepProposal(**proposal(**changes)))


def test_finish_is_evidence_backed_proposal_not_authorization():
    from asset_based_agent.browser_contracts import (
        BrowserStepProposal,
        BrowserStepRequest,
        validate_browser_step,
    )
    result = validate_browser_step(BrowserStepRequest(**request_data()), BrowserStepProposal(
        **proposal(action='finish', target='', evidence='Project alpha exists')))
    assert result.action == 'finish' and 'permission' not in result.model_dump()


@pytest.mark.parametrize('action,value', [('scroll','down'), ('scroll','up'), ('wait','500')])
def test_bounded_view_actions(action, value):
    from asset_based_agent.browser_contracts import (
        BrowserStepProposal,
        BrowserStepRequest,
        validate_browser_step,
    )
    data = request_data()
    data['scope']['actions'] += ['scroll', 'wait']
    assert validate_browser_step(BrowserStepRequest(**data), BrowserStepProposal(
        **proposal(action=action, target='', value=value))).action == action


@pytest.mark.parametrize('action,value', [('scroll','99999'), ('scroll','window.eval()'),
                                         ('wait','0'), ('wait','5001'), ('wait','1.5')])
def test_unbounded_view_actions_rejected(action, value):
    from asset_based_agent.browser_contracts import (
        BrowserStepProposal,
        BrowserStepRequest,
        validate_browser_step,
    )
    data = request_data()
    data['scope']['actions'] += ['scroll', 'wait']
    with pytest.raises(ValueError):
        validate_browser_step(BrowserStepRequest(**data), BrowserStepProposal(
            **proposal(action=action, target='', value=value)))


def test_browser_step_endpoint_requires_authentication(client):
    assert client.post('/api/v1/agent/browser-step', json=request_data()).status_code == 401
    assert client.get('/api/v1/capabilities').json()['capabilities']['browser_step'] == 1
    assert client.get('/api/v1/capabilities').json()['capabilities']['browser_view_actions'] == 1


def test_invalid_model_response_is_sanitized():
    from asset_based_agent.browser_contracts import BrowserStepRequest
    from asset_based_agent.report_review_server.services.auth_service import (
        ServiceError,
    )
    from asset_based_agent.report_review_server.services.browser_step import (
        propose_browser_step,
    )
    class Meter:
        def execute(self, *args, **kwargs):
            return SimpleNamespace(payload={'choices':[{'message':{'content':'synthetic-secret-invalid-json'}}]})
    with pytest.raises(ServiceError) as error:
        propose_browser_step(Meter(), None, 'user', BrowserStepRequest(**request_data()))
    assert 'synthetic-secret' not in str(error.value)


def test_authenticated_browser_step_uses_account_context(client, monkeypatch):
    from asset_based_agent.browser_contracts import BrowserStepProposal
    from asset_based_agent.report_review_server import api
    token = client.post('/api/v1/auth/login', json={
        'username':'admin', 'password':'AdminPassword123!', 'client_instance_id':'test',
    }).json()['access_token']
    calls = []
    def fake(metered, db, user_id, payload):
        calls.append((user_id, payload.request_id))
        return BrowserStepProposal(**proposal())
    monkeypatch.setattr(api, 'propose_browser_step', fake)
    response = client.post('/api/v1/agent/browser-step', json=request_data(),
                           headers={'Authorization':'Bearer '+token})
    assert response.status_code == 200 and response.json()['target'] == '1'
    assert calls[0][0] and calls[0][1] == 'r'
    schema = client.get('/openapi.json').json()
    assert schema['components']['schemas']['BrowserStepRequest']['additionalProperties'] is False
