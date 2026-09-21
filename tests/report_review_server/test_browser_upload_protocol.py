import pytest

from asset_based_agent.browser_contracts import (
    BrowserStepProposal,
    BrowserStepRequest,
    validate_browser_step,
)


def request():
    return BrowserStepRequest.model_validate({'request_id':'r','model_id':'m','task_id':'t',
        'sequence':1,'goal':'Upload the generated report to project 001',
        'scope':{'origins':['https://example.com'],'actions':['observe','upload']},
        'upload_artifacts':[{'id':'artifact-1','name':'report.docx','size':100,'sha256':'a'*64}],
        'observation':{'nonce':'n','page_version':1,'origin':'https://example.com','text':'Project 001',
            'controls':[{'id':'1','kind':'file','text':'Report','disabled':False}],'truncated':False}})


def proposal(**changes):
    return BrowserStepProposal.model_validate({'request_id':'r','action':'upload','target':'1',
        'artifact_id':'artifact-1','object_label':'Project 001','summary':'Upload generated report',**changes})


def test_upload_proposal_uses_bounded_artifact_and_observed_field():
    assert validate_browser_step(request(), proposal()).action == 'upload'


@pytest.mark.parametrize('changes', [{'artifact_id':'unknown'}, {'target':'2'}, {'object_label':''},
    {'path':'D:/raw.docx'}, {'value':'D:/raw.docx'}, {'url':'https://example.com/upload'}])
def test_upload_rejects_invented_source_field_or_path(changes):
    with pytest.raises(ValueError): validate_browser_step(request(), proposal(**changes))


def test_upload_metadata_has_no_local_path_and_requires_scope(client):
    assert client.get('/api/v1/capabilities').json()['capabilities']['browser_upload'] == 1
    data = request().model_dump()
    data['upload_artifacts'][0]['path'] = 'D:/raw.docx'
    with pytest.raises(ValueError): BrowserStepRequest.model_validate(data)
    data = request().model_dump()
    data['scope']['actions'] = ['observe']
    with pytest.raises(ValueError): BrowserStepRequest.model_validate(data)


def test_upload_model_request_is_metadata_only_and_uses_existing_meter():
    import json
    from types import SimpleNamespace

    from asset_based_agent.report_review_server.services.browser_step import (
        propose_browser_step,
    )
    calls = []
    class Meter:
        def execute(self, db, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(payload={'choices':[{'message':{'content':proposal().model_dump_json()}}]})
    assert propose_browser_step(Meter(), None, 'synthetic-user', request()).artifact_id == 'artifact-1'
    call = calls[0]
    assert call['client_request_id'] == 'browser:r' and call['user_id'] == 'synthetic-user'
    content = json.loads(call['payload']['messages'][1]['content'])
    assert set(content['upload_artifacts'][0]) == {'id','name','size','sha256'}
    assert 'model_id' not in content
