import threading

import httpx
import pytest

from asset_based_agent.report_review_app.services.remote_auth_service import (
    MemoryCredentialStore,
    RemoteAuthenticationError,
    RemoteSessionClient,
)
from asset_based_agent.report_review_app.services.task_cancellation import TaskCancelled


def payload():
    return {
        'request': {'request_id': 'r', 'model_id': 'm', 'message_id': 'msg', 'prompt': '审核新报告',
                    'files': [{'id': 'f', 'name': 'new.docx', 'sha256': 'a' * 64}],
                    'skills': [{'id': 'report.review', 'name': 'review', 'adapter': 'report.review',
                                'description': 'readonly'}]},
        'understanding': {'message_intent': 'execute', 'goal': '审核', 'targets': ['f'],
                          'references': [], 'excluded': [], 'constraints': [], 'deliverables': [],
                          'missing_inputs': [], 'evidence_message_ids': ['msg'],
                          'skill_ids': ['report.review'], 'next_action': 'plan', 'reply': '审核新报告'}}


@pytest.mark.parametrize('mode', ['valid', 'invalid', 'unsupported', 'cancel_precheck', 'cancel_response'])
def test_remote_planner_capability_scope_and_cancellation(mode):
    calls, cancel = [], threading.Event()
    def handler(request):
        calls.append(request.url.path)
        if request.method == 'GET':
            if mode == 'cancel_precheck':
                cancel.set()
            return httpx.Response(200, json={'schema_version': 1, 'protocol_version': 1,
                                            'capabilities': {} if mode == 'unsupported' else {'task_planning': 1}})
        assert request.url.path == '/api/v1/agent/plan'
        assert request.headers['authorization'] == 'Bearer synthetic'
        if mode == 'cancel_response':
            cancel.set()
        return httpx.Response(200, json={'request_id': 'other' if mode == 'invalid' else 'r',
            'steps': [{'step_id': 'one', 'skill_id': 'report.review', 'goal': '审核新报告',
                       'inputs': [{'kind': 'file', 'ref': 'f', 'role': 'target'}], 'dependencies': []}]})
    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        client = RemoteSessionClient('https://review.example/api/v1', client_instance_id='test',
                                     credential_store=MemoryCredentialStore(), http_client=http)
        client.access_token = 'synthetic'
        if mode == 'valid':
            assert client.propose_plan(payload(), cancel=cancel)['request_id'] == 'r'
        elif mode.startswith('cancel'):
            with pytest.raises(TaskCancelled):
                client.propose_plan(payload(), cancel=cancel)
        else:
            with pytest.raises(RemoteAuthenticationError):
                client.propose_plan(payload(), cancel=cancel)
    assert calls == (['/api/v1/capabilities'] if mode in {'unsupported', 'cancel_precheck'} else
                     ['/api/v1/capabilities', '/api/v1/agent/plan'])
