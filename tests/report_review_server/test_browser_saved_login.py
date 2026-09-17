import pytest

from asset_based_agent.browser_contracts import (
    BrowserStepProposal,
    BrowserStepRequest,
    validate_browser_step,
)


def request():
    return BrowserStepRequest(
        request_id='r', model_id='m', task_id='t', sequence=1, goal='Login locally',
        scope={'origins':['https://example.com'], 'actions':['observe', 'login']},
        observation={'nonce':'n', 'page_version':1, 'origin':'https://example.com',
                     'text':'Login', 'controls':[], 'truncated':False},
    )


def test_saved_login_is_only_a_local_request_without_credentials():
    result = validate_browser_step(request(), BrowserStepProposal(
        request_id='r', action='login', summary='Request local account selection'))
    assert result.action == 'login'
    assert result.target == result.value == result.url == ''


@pytest.mark.parametrize('field,value', [
    ('target', '1'), ('value', 'account-or-password'),
    ('url', 'https://example.com'), ('credential_id', 'secret-key'),
])
def test_model_cannot_select_account_or_supply_login_material(field, value):
    with pytest.raises(ValueError):
        validate_browser_step(request(), BrowserStepProposal.model_validate({
            'request_id':'r', 'action':'login', 'summary':'Login', field:value}))


def test_saved_login_requires_observation_and_scope():
    proposal = BrowserStepProposal(request_id='r', action='login', summary='Login')
    for data in [request().model_dump() | {'observation':None},
                 request().model_dump() | {'scope':{
                     'origins':['https://example.com'], 'actions':['observe']}}]:
        with pytest.raises(ValueError):
            validate_browser_step(BrowserStepRequest.model_validate(data), proposal)


def test_server_advertises_saved_login_protocol(client):
    assert client.get('/api/v1/capabilities').json()['capabilities']['browser_saved_login'] == 1
