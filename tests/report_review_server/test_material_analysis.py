import json
from types import SimpleNamespace

import pytest

from asset_based_agent.report_review_server.services.auth_service import ServiceError
from asset_based_agent.report_review_server.services.material_analysis import MaterialRequest, analyze_materials


def test_material_analysis_uses_metering_and_returns_no_costs():
    class Meter:
        def execute(self, db, **kwargs):
            assert kwargs['user_id'] == 'user'
            assert kwargs['client_request_id'] == 'material:run'
            assert kwargs['estimated_usage'].output_tokens == 8192
            assert kwargs['payload']['max_tokens'] == 8192
            return SimpleNamespace(payload={'choices': [{'message': {'content': json.dumps({
                'assignments': [{'file_id': 'file', 'role': 'bank_statement', 'reason': '账户余额表头'}]})}}]})
    request = MaterialRequest(model_id='model', request_id='run', files=[{
        'file_id': 'file', 'name': 'file.xlsx', 'text': '账户余额'}])
    plan = analyze_materials(Meter(), None, 'user', request)
    assert set(plan.model_dump()) == {'assignments'}


def test_material_analysis_rejects_fabricated_file():
    class Meter:
        def execute(self, *args, **kwargs):
            return SimpleNamespace(payload={'choices': [{'message': {'content': json.dumps({
                'assignments': [{'file_id': 'outside', 'role': 'other', 'reason': 'x'}]})}}]})
    request = MaterialRequest(model_id='model', request_id='run', files=[{
        'file_id': 'file', 'name': 'file.xlsx', 'text': 'x'}])
    with pytest.raises(ServiceError):
        analyze_materials(Meter(), None, 'user', request)


def test_material_endpoint_requires_login(client):
    response = client.post('/api/v1/material-analysis', json={
        'request_id': 'run', 'model_id': 'model',
        'files': [{'file_id': 'file', 'name': 'file.xlsx', 'text': 'x'}]})
    assert response.status_code == 401


def test_material_endpoint_rejects_original_path_field(client):
    from .conftest import bearer, login
    user = login(client, 'admin', 'AdminPassword123!', instance='analysis-test')
    response = client.post('/api/v1/material-analysis', headers=bearer(user['access_token']), json={
        'request_id': 'run', 'model_id': 'model',
        'files': [{'file_id': 'file', 'name': 'file.xlsx', 'text': 'x', 'path': 'private/path'}]})
    assert response.status_code == 422
    assert 'private/path' not in response.text
