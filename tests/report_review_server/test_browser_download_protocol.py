import pytest

from asset_based_agent.browser_contracts import (
    BrowserStepProposal,
    BrowserStepRequest,
    validate_browser_step,
)


def request():
    return BrowserStepRequest(request_id='r',model_id='m',task_id='t',sequence=1,goal='Download the report',
        scope={'origins':['https://example.com'],'actions':['observe','download']},
        observation={'nonce':'n','page_version':1,'origin':'https://example.com','text':'Report',
            'truncated':False,'controls':[{'id':'1','kind':'link','text':'Download report','disabled':False}]})


def test_download_uses_observed_target_without_model_url_or_destination():
    assert validate_browser_step(request(), BrowserStepProposal(request_id='r',action='download',
        target='1',summary='Download the selected report')).action=='download'


@pytest.mark.parametrize('change',[{'target':'2'},{'url':'https://example.com/file'},
                                  {'value':'D:/secret.txt'},{'path':'D:/secret.txt'}])
def test_download_cannot_invent_target_or_save_path(change):
    with pytest.raises(ValueError):
        validate_browser_step(request(),BrowserStepProposal.model_validate({
            'request_id':'r','action':'download','target':'1','summary':'Download',**change}))


def test_download_server_capability_and_metadata_boundary(client):
    assert client.get('/api/v1/capabilities').json()['capabilities']['browser_download']==1
    data=request().model_dump()
    assert 'completed_downloads' not in data
    item={'name':'report.xlsx','size':4,'origin':'https://example.com'}
    assert BrowserStepRequest.model_validate(data | {'completed_downloads':[item]}).completed_downloads[0].size==4
    for change in ({'path':'D:/report.xlsx'}, {'origin':'https://other.test'}):
        with pytest.raises(ValueError):
            BrowserStepRequest.model_validate(data | {'completed_downloads':[item | change]})


def test_generated_download_requires_explicit_client_support(client):
    data=request().model_dump()
    data['observation']['controls'][0]['kind']='button'
    proposal=BrowserStepProposal(request_id='r',action='download',target='1',summary='Download')
    with pytest.raises(ValueError): validate_browser_step(BrowserStepRequest.model_validate(data),proposal)
    enabled=BrowserStepRequest.model_validate(data | {'generated_downloads':True})
    assert validate_browser_step(enabled,proposal).target=='1'
    assert client.get('/api/v1/capabilities').json()['capabilities']['browser_generated_download']==1
    assert 'generated_downloads' not in request().model_dump()
    data['scope']['actions']=['observe']
    with pytest.raises(ValueError): BrowserStepRequest.model_validate(data | {'generated_downloads':True})
