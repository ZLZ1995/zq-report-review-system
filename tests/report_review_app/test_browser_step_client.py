import json
import threading

import httpx
import pytest

from asset_based_agent.report_review_app.services.remote_auth_service import (
    MemoryCredentialStore,
    RemoteAuthenticationError,
    RemoteSessionClient,
)
from asset_based_agent.report_review_app.services.task_cancellation import TaskCancelled


@pytest.mark.parametrize('case', ['valid', 'invalid', 'cancel'])
def test_browser_step_checks_capability_cancel_and_reply(case):
    cancel = threading.Event()
    calls = []
    def handler(request):
        calls.append(request.url.path)
        if request.method == 'GET':
            if case == 'cancel': cancel.set()
            return httpx.Response(200, json={'schema_version':1, 'protocol_version':1,
                                            'capabilities':{'browser_step':1}})
        return httpx.Response(200, json={'request_id':'r', 'action':'navigate',
            'url':'https://evil.example' if case == 'invalid' else 'https://example.com',
            'summary':'Open website'})
    payload = {'request_id':'r', 'model_id':'m', 'task_id':'t', 'sequence':1,
               'goal':'Open website', 'scope':{'origins':['https://example.com'], 'actions':['navigate']}}
    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        client = RemoteSessionClient('https://review.example/api/v1', client_instance_id='test',
                                     credential_store=MemoryCredentialStore(), http_client=http)
        client.access_token = 'synthetic'
        if case == 'valid': assert client.propose_browser_step(payload, cancel=cancel)['action'] == 'navigate'
        else:
            with pytest.raises(TaskCancelled if case == 'cancel' else RemoteAuthenticationError):
                client.propose_browser_step(payload, cancel=cancel)
    assert calls == (['/api/v1/capabilities'] if case == 'cancel' else
                      ['/api/v1/capabilities', '/api/v1/agent/browser-step'])


@pytest.mark.parametrize('supported', [False, True])
def test_understanding_only_advertises_browser_supported_by_server(supported):
    posted = []
    def handler(request):
        if request.method == 'GET':
            capabilities = {'task_understanding':1}
            if supported:
                capabilities['browser_step'] = 1
            return httpx.Response(200, json={'schema_version':1, 'protocol_version':1,
                                            'capabilities':capabilities})
        posted.append(json.loads(request.content))
        return httpx.Response(200, json={
            'message_intent':'consult', 'goal':'Explain available capabilities',
            'targets':[], 'references':[], 'excluded':[], 'constraints':[],
            'deliverables':[], 'missing_inputs':[], 'evidence_message_ids':['msg'],
            'skill_ids':[], 'next_action':'answer', 'reply':'Available capabilities only.',
        })
    payload = {'request_id':'r', 'model_id':'m', 'message_id':'msg', 'prompt':'What can you do?',
               'skills':[{'id':'browser.task', 'adapter':'browser.task',
                          'name':'Browser', 'description':'Native browser'}]}
    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        client = RemoteSessionClient('https://review.example/api/v1', client_instance_id='test',
                                     credential_store=MemoryCredentialStore(), http_client=http)
        client.access_token = 'synthetic'
        assert client.understand_task(payload)['next_action'] == 'answer'
    assert len(posted) == 1
    assert any(s['id']=='browser.task' for s in posted[0]['skills']) is supported
    assert payload['skills'][0]['id']=='browser.task', 'Do not mutate the caller request'


@pytest.mark.parametrize('capabilities', [None, {'browser_step':1}])
@pytest.mark.parametrize('action', ['wait', 'login', 'download', 'upload'])
def test_old_server_cannot_receive_new_view_actions(capabilities, action):
    from asset_based_agent.report_review_app.services.remote_auth_service import (
        ServerCapabilityUnavailable,
    )
    posts=[]
    def handler(request):
        if request.method == 'POST':
            posts.append(True)
            return httpx.Response(200, json={'request_id':'r','action':'ask','summary':'Which?'})
        if request.url.path.endswith('openapi.json'):
            return httpx.Response(200,json={'paths':{'/api/v1/agent/browser-step':{'post':{}}}})
        return (httpx.Response(404) if capabilities is None else httpx.Response(200,json={
            'schema_version':1,'protocol_version':1,'capabilities':capabilities}))
    payload={'request_id':'r','model_id':'m','task_id':'t','sequence':1,'goal':'Read',
             'scope':{'origins':['https://example.com'],'actions':['observe',action]}}
    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        client=RemoteSessionClient('https://review.example/api/v1',client_instance_id='test',
            credential_store=MemoryCredentialStore(),http_client=http)
        client.access_token='synthetic'
        with pytest.raises(ServerCapabilityUnavailable): client.propose_browser_step(payload)
    assert posts==[]


def test_saved_login_capable_server_receives_only_observation_not_credentials():
    posted = []
    def handler(request):
        if request.method == 'GET':
            return httpx.Response(200, json={'schema_version':1, 'protocol_version':1,
                'capabilities':{'browser_step':1, 'browser_saved_login':1}})
        posted.append(json.loads(request.content))
        return httpx.Response(200, json={'request_id':'r','action':'login','summary':'Choose locally'})
    payload={'request_id':'r','model_id':'m','task_id':'t','sequence':1,'goal':'Login',
             'scope':{'origins':['https://example.com'],'actions':['observe','login']},
             'observation':{'nonce':'n','page_version':1,'origin':'https://example.com',
                            'text':'Login','controls':[],'truncated':False}}
    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        client=RemoteSessionClient('https://review.example/api/v1',client_instance_id='test',
            credential_store=MemoryCredentialStore(),http_client=http)
        client.access_token='synthetic'
        assert client.propose_browser_step(payload)['action']=='login'
    assert len(posted)==1
    assert set(posted[0]) == set(payload) | {'schema_version'}


@pytest.mark.parametrize('supported, malicious', [(False, False), (True, False), (False, True)])
def test_generated_download_negotiation_preserves_old_link_downloads(supported, malicious):
    posted=[]
    def handler(request):
        if request.method=='GET':
            caps={'browser_step':1,'browser_download':1}
            if supported: caps['browser_generated_download']=1
            return httpx.Response(200,json={'schema_version':1,'protocol_version':1,'capabilities':caps})
        posted.append(json.loads(request.content))
        return httpx.Response(200,json={'request_id':'r','action':'download',
            'target':'2' if supported or malicious else '1','summary':'Download'})
    payload={'request_id':'r','model_id':'m','task_id':'t','sequence':1,'goal':'Download',
        'generated_downloads':True,'scope':{'origins':['https://example.com'],'actions':['observe','download']},
        'observation':{'nonce':'n','page_version':1,'origin':'https://example.com','text':'Files',
            'truncated':False,'controls':[{'id':'1','kind':'link','text':'File','disabled':False},
                {'id':'2','kind':'button','text':'Generate file','disabled':False}]}}
    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        client=RemoteSessionClient('https://review.example/api/v1',client_instance_id='test',
            credential_store=MemoryCredentialStore(),http_client=http)
        client.access_token='synthetic'
        if malicious:
            with pytest.raises(RemoteAuthenticationError): client.propose_browser_step(payload)
        else:
            assert client.propose_browser_step(payload)['target']==('2' if supported else '1')
    assert bool(posted[0].get('generated_downloads')) is supported
    assert payload['generated_downloads'] is True
