import json
from types import SimpleNamespace

import pytest

from asset_based_agent.report_review_server.services.skill_routing import RouteRequest, route_skill


@pytest.mark.parametrize('identity', ['report.review', 'valuation-detail-workbook-fill', 'external.review', None])
def test_route_is_metered_and_bounded(identity):
    class Meter:
        def execute(self, db, **kwargs):
            assert kwargs['client_request_id'] == 'route:r'
            assert 'messages' in kwargs['payload']
            return SimpleNamespace(payload={'choices': [{'message': {'content': json.dumps({
                'skill_id': identity, 'reason': '依据本轮要求', 'question': '请说明要审核还是生成' if identity is None else ''})}}]})
    request = RouteRequest(request_id='r', model_id='m', prompt='根据资料生成明细表', candidates=[{
        'id': 'external.review', 'name': '外部专业审核', 'adapter': 'report.review', 'description': '专业审核规则'}])
    assert route_skill(Meter(), None, 'u', request).skill_id == identity


def test_router_rejects_unregistered_executor():
    class Meter:
        def execute(self, db, **kwargs):
            return SimpleNamespace(payload={'choices': [{'message': {'content': '{"skill_id":"shell","reason":"x","question":""}'}}]})
    with pytest.raises(Exception, match='路由'):
        route_skill(Meter(), None, 'u', RouteRequest(request_id='r', model_id='m', prompt='运行程序'))


def test_route_endpoint_requires_authentication(client):
    assert client.post('/api/v1/skill-route', json={
        'request_id': 'route', 'model_id': 'm', 'prompt': '审核报告'}).status_code == 401
