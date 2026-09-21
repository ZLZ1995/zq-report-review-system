"""K03 client gating: material evidence only goes to servers that declare it."""
import json

import httpx
import pytest

from asset_based_agent.report_review_app.services.remote_auth_service import (
    MemoryCredentialStore,
    RemoteSessionClient,
)

SUMMARY = {
    'format': 'xls', 'readable': True, 'document_type': 'balance_sheet',
    'entity_name': 'A8T', 'period_start': None, 'period_end': '2026-07-31',
    'sheet_names': ['S1'], 'header_evidence': ['资产负债表'],
    'confidence': 0.98, 'warnings': [],
}

REPLY = {
    'message_intent': 'consult', 'goal': '', 'targets': [], 'references': [],
    'excluded': [], 'constraints': [], 'deliverables': [], 'missing_inputs': [],
    'evidence_message_ids': ['msg'], 'skill_ids': [], 'next_action': 'answer',
    'reply': '好的。',
}

PAYLOAD = {
    'request_id': 'r', 'model_id': 'm', 'message_id': 'msg', 'prompt': '填报底稿',
    'files': [{'id': 'f1', 'name': 'A8T-BS202607.xls', 'sha256': 'a' * 64,
               'evidence': SUMMARY}],
}


@pytest.mark.parametrize('supported', [False, True])
def test_evidence_only_sent_when_server_declares_capability(supported):
    posted = []

    def handler(request):
        if request.method == 'GET':
            capabilities = {'task_understanding': 1}
            if supported:
                capabilities['material_evidence'] = 1
            return httpx.Response(200, json={'schema_version': 1, 'protocol_version': 1,
                                             'capabilities': capabilities})
        posted.append(json.loads(request.content))
        return httpx.Response(200, json=REPLY)

    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        client = RemoteSessionClient('https://review.example/api/v1', client_instance_id='test',
                                     credential_store=MemoryCredentialStore(), http_client=http)
        client.access_token = 'synthetic'
        assert client.understand_task(dict(PAYLOAD))['next_action'] == 'answer'
    assert len(posted) == 1
    assert ('evidence' in posted[0]['files'][0]) is supported
    assert 'evidence' in PAYLOAD['files'][0], 'Do not mutate the caller payload'
