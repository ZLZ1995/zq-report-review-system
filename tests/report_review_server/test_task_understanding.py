import json
from types import SimpleNamespace

import pytest


def request_data():
    return {'schema_version': 1, 'request_id': 'r', 'model_id': 'm',
            'message_id': 'msg', 'prompt': '只审核新报告，旧文件不要审核',
            'files': [{'id': 'new', 'name': '新报告.docx', 'sha256': 'a' * 64},
                      {'id': 'old', 'name': '旧报告.docx', 'sha256': 'b' * 64}],
            'skills': [{'id': 'report.review', 'name': '报告审核',
                        'adapter': 'report.review', 'description': '只读审核'}]}


def result_data():
    return {'schema_version': 1, 'message_intent': 'execute', 'goal': '审核新报告',
            'targets': ['new'], 'references': [], 'excluded': ['old'],
            'constraints': ['不修改原件'], 'deliverables': ['审核意见'],
            'missing_inputs': [], 'evidence_message_ids': ['msg'],
            'skill_ids': ['report.review'], 'next_action': 'plan',
            'reply': '本轮仅审核新报告。'}


class Meter:
    def __init__(self, output):
        self.output = output
        self.calls = []

    def execute(self, db, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(payload={'choices': [{'message': {'content': json.dumps(self.output)}}]})


def test_understanding_is_metered_and_separates_target_from_exclusion():
    from asset_based_agent.agent_contracts import UnderstandingRequest
    from asset_based_agent.report_review_server.services.task_understanding import (
        understand_task,
    )
    meter = Meter(result_data())
    result = understand_task(meter, None, 'user', UnderstandingRequest(**request_data()))
    assert result.targets == ['new'] and result.excluded == ['old']
    assert meter.calls[0]['client_request_id'] == 'understand:r'
    assert meter.calls[0]['payload']['response_format'] == {'type': 'json_object'}
    assert 'permissions' not in result.model_dump()


@pytest.mark.parametrize('patch', [
    {'targets': ['unknown']}, {'excluded': ['new']}, {'skill_ids': ['shell']},
    {'evidence_message_ids': ['invented']}, {'permissions': {'write': True}},
    {'schema_version': True}, {'next_action': 'answer'},
])
def test_untrusted_model_cannot_invent_references_permissions_or_action(patch):
    from asset_based_agent.agent_contracts import UnderstandingRequest
    from asset_based_agent.report_review_server.services.auth_service import (
        ServiceError,
    )
    from asset_based_agent.report_review_server.services.task_understanding import (
        understand_task,
    )
    with pytest.raises(ServiceError, match='理解'):
        understand_task(Meter({**result_data(), **patch}), None, 'u',
                        UnderstandingRequest(**request_data()))


def test_consultation_without_attachments_does_not_plan_execution():
    from asset_based_agent.agent_contracts import UnderstandingRequest
    from asset_based_agent.report_review_server.services.task_understanding import (
        understand_task,
    )
    request = UnderstandingRequest(**{**request_data(), 'files': [], 'prompt': '解释一下审核功能'})
    output = {**result_data(), 'message_intent': 'consult', 'next_action': 'answer',
              'targets': [], 'excluded': [], 'skill_ids': [], 'deliverables': [],
              'reply': '审核默认只读。'}
    assert understand_task(Meter(output), None, 'u', request).next_action == 'answer'


def test_request_rejects_raw_paths_duplicate_ids_and_unbounded_context():
    from asset_based_agent.agent_contracts import UnderstandingRequest
    for patch in ({'files': [{'id': 'f', 'name': 'x', 'sha256': 'a' * 64, 'path': 'D:/private'}]},
                  {'files': request_data()['files'] * 2},
                  {'prompt': 'x' * 12001}):
        with pytest.raises(ValueError):
            UnderstandingRequest(**{**request_data(), **patch})


def test_understanding_endpoint_requires_authentication(client):
    response = client.post('/api/v1/agent/understand', json=request_data())
    assert response.status_code == 401
    assert client.get('/api/v1/capabilities').json()['capabilities']['task_understanding'] == 1


def test_authenticated_endpoint_uses_validated_request_and_response(client, monkeypatch):
    from asset_based_agent.agent_contracts import TaskUnderstanding
    from asset_based_agent.report_review_server import api
    token = client.post('/api/v1/auth/login', json={
        'username': 'admin', 'password': 'AdminPassword123!', 'client_instance_id': 'test',
    }).json()['access_token']
    def fake(metered, db, user_id, payload):
        assert user_id and payload.request_id == 'r'
        return TaskUnderstanding(**result_data())
    monkeypatch.setattr(api, 'understand_task', fake)
    response = client.post('/api/v1/agent/understand', json=request_data(),
                           headers={'Authorization': 'Bearer ' + token})
    assert response.status_code == 200
    assert response.json()['targets'] == ['new']
