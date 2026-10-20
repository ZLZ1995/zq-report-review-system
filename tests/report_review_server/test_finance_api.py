"""Shared data credentials never leave the control plane; data calls are unmetered."""
import json
from types import SimpleNamespace
from uuid import uuid4

from .conftest import bearer, login


def admin_headers(client):
    return bearer(login(client, 'admin', 'AdminPassword123!', instance='finance')['access_token'])


def test_finance_authentication_and_key_encryption(client):
    assert client.get('/api/v1/finance/tools').status_code == 401
    headers = admin_headers(client)
    key = uuid4().hex
    response = client.put('/api/v1/admin/finance/credential', headers=headers,
                          json={'api_key': key})
    assert response.status_code == 200
    assert key not in response.text
    from asset_based_agent.report_review_server.finance_models import FinanceCredential
    with client.app.state.session_factory() as db:
        row = db.get(FinanceCredential, 'fuyao')
        assert key not in row.ciphertext
    catalog = client.get('/api/v1/finance/tools', headers=headers).json()
    assert len(catalog['tools']) == 113
    assert key not in json.dumps(catalog)


def test_data_query_uses_shared_key_and_does_not_charge_wallet(client):
    headers = admin_headers(client)
    client.put('/api/v1/admin/finance/credential', headers=headers,
               json={'api_key': 'synthetic-shared-key'})
    service = client.app.state.finance_service
    calls = []
    def query(name, arguments, key):
        calls.append((name, arguments, key))
        return {'source': 'internal-provenance', 'response': {'code': 0, 'data': [{'value': 123}]}}
    service.gateway.query = query
    before = client.get('/api/v1/account/balance', headers=headers).json()
    name = 'get_a_share_calendar_trading_days'
    response = client.post('/api/v1/finance/query', headers=headers,
                          json={'tool': name, 'arguments': {}})
    assert response.status_code == 200
    assert calls[-1][2] == 'synthetic-shared-key'
    assert 'internal-provenance' not in response.text
    assert 'synthetic-shared-key' not in response.text
    assert client.get('/api/v1/account/balance', headers=headers).json() == before


def test_unknown_tool_rejected_and_macro_needs_no_key(client):
    headers = admin_headers(client)
    assert client.post('/api/v1/finance/query', headers=headers,
                       json={'tool': 'run_code', 'arguments': {}}).status_code == 422
    response = client.post('/api/v1/finance/query', headers=headers,
                           json={'tool': 'macro_indicator_search',
                                 'arguments': {'keyword': '居民消费价格'}})
    assert response.status_code == 200
    assert response.json()['data']['total'] > 0


def test_user_cannot_read_or_replace_shared_credential(client):
    headers = admin_headers(client)
    made = client.post('/api/v1/admin/users', headers=headers, json={
        'username': 'finance-user', 'display_name': 'Finance User',
        'temporary_password': 'User12345'})
    assert made.status_code == 201
    user = bearer(login(client, 'finance-user', 'User12345', instance='user')['access_token'])
    assert client.get('/api/v1/admin/finance/credential', headers=user).status_code == 403
    assert client.put('/api/v1/admin/finance/credential', headers=user,
                      json={'api_key': 'other-key'}).status_code == 403


def test_natural_query_uses_existing_metering_and_idempotent_receipt(client):
    headers = admin_headers(client)
    service = client.app.state.finance_service
    metered_calls = []
    plans = [{'tool': 'fuyao_tool_help', 'arguments': {'tool': 'macro_lpr'}},
             {'tool': 'macro_lpr', 'arguments': {'as_of': '2025-01-01'}},
             {'done': True, 'reply': '999999 is fabricated and must not appear'}]
    def execute(db, **kwargs):
        metered_calls.append(kwargs)
        return SimpleNamespace(payload={'choices': [{'message': {'content': json.dumps(plans.pop(0))}}]})
    service.metered = SimpleNamespace(execute=execute)
    service.gateway.query = lambda name, args, key, **kwargs: (
        {'name': name, 'inputSchema': {}} if name == 'fuyao_tool_help' else
        {'unit': '%', 'observations': [{'date': '2024-12-20', 'one_year_pct': 3.1}]})
    payload = {'request_id': uuid4().hex, 'model_id': 'synthetic-model', 'prompt': '查询LPR'}
    first = client.post('/api/v1/finance/ask', headers=headers, json=payload)
    assert first.status_code == 200, first.text
    assert first.json()['datasets'][0]['data']['observations'][0]['one_year_pct'] == 3.1
    assert '999999' not in first.text
    replay = client.post('/api/v1/finance/ask', headers=headers, json=payload)
    assert replay.json() == first.json()
    assert len(metered_calls) == 3
    assert [item['client_request_id'] for item in metered_calls] == [
        f'finance:{payload["request_id"]}:{i}' for i in range(3)]
    assert client.post('/api/v1/finance/ask', headers=headers,
                       json={**payload, 'prompt': 'other'}).status_code == 409


def test_cancel_before_submit_prevents_any_model_call(client):
    headers = admin_headers(client)
    request_id = uuid4().hex
    assert client.post(f'/api/v1/finance/requests/{request_id}/cancel', headers=headers).json()['status'] == 'cancelled'
    service = client.app.state.finance_service
    def forbidden(*args, **kwargs):
        raise AssertionError('cancelled request reached the model')
    service.metered = SimpleNamespace(execute=forbidden)
    response = client.post('/api/v1/finance/ask', headers=headers, json={
        'request_id': request_id, 'model_id': 'm', 'prompt': '查LPR'})
    assert response.status_code == 409
    assert response.json()['error']['code'] == 'finance_cancelled'


def test_cancellation_between_model_and_data_stops_next_call(client):
    headers = admin_headers(client)
    request_id = uuid4().hex
    service = client.app.state.finance_service
    def execute(db, **kwargs):
        with client.app.state.session_factory() as other:
            user_id = kwargs['user_id']
            service.cancel(other, user_id, request_id)
        return SimpleNamespace(payload={'choices': [{'message': {'content': json.dumps({
            'tool': 'macro_lpr', 'arguments': {}})}}]})
    service.metered = SimpleNamespace(execute=execute)
    def forbidden(*args, **kwargs):
        raise AssertionError('cancelled request reached data source')
    service.gateway.query = forbidden
    response = client.post('/api/v1/finance/ask', headers=headers, json={
        'request_id': request_id, 'model_id': 'm', 'prompt': '查LPR'})
    assert response.status_code == 409
    assert client.get(f'/api/v1/finance/requests/{request_id}', headers=headers).json()['status'] == 'cancelled'


def test_finance_result_isolated_by_account_and_expires(client):
    from datetime import timedelta

    from asset_based_agent.report_review_server.finance_models import FinanceRequest
    from asset_based_agent.report_review_server.models import utc_now
    from asset_based_agent.report_review_server.services.temporary_data_cleanup import (
        cleanup_expired_temporary_data,
    )
    headers = admin_headers(client)
    request_id = uuid4().hex
    identity = login(client, 'admin', 'AdminPassword123!', instance='read-result')
    headers = bearer(identity['access_token'])
    user_id = identity['user']['user_id']
    with client.app.state.session_factory() as db:
        db.add(FinanceRequest(user_id=user_id, request_id=request_id, request_hash='x',
                              status='succeeded', result_ciphertext='encrypted-fixture',
                              expires_at=utc_now() - timedelta(seconds=1)))
        db.commit()
        cleanup_expired_temporary_data(db)
        assert db.get(FinanceRequest, (user_id, request_id)).result_ciphertext is None
    assert client.get(f'/api/v1/finance/requests/{request_id}', headers=headers).status_code == 410
    assert client.get(f'/api/v1/finance/requests/{uuid4().hex}', headers=headers).status_code == 404


def test_invalid_tool_plan_is_rejected_before_data_call(client):
    headers = admin_headers(client)
    service = client.app.state.finance_service
    service.metered = SimpleNamespace(execute=lambda *a, **k: SimpleNamespace(payload={
        'choices': [{'message': {'content': '{"tool":"run_code","arguments":{}}'}}]}))
    response = client.post('/api/v1/finance/ask', headers=headers, json={
        'request_id': uuid4().hex, 'model_id': 'm', 'prompt': '查询LPR'})
    assert response.status_code == 422


def test_abandoned_finance_request_becomes_terminal_without_repeating_model(client):
    import hashlib
    from datetime import timedelta

    from asset_based_agent.report_review_server.finance_api import FinanceAsk
    from asset_based_agent.report_review_server.finance_models import FinanceRequest
    from asset_based_agent.report_review_server.models import utc_now

    identity = login(client, 'admin', 'AdminPassword123!', instance='interrupted-finance')
    headers = bearer(identity['access_token'])
    user_id, request_id = identity['user']['user_id'], uuid4().hex
    payload = {'request_id': request_id, 'model_id': 'm', 'prompt': '查LPR'}
    fingerprint = hashlib.sha256(FinanceAsk(**payload).model_dump_json().encode()).hexdigest()
    with client.app.state.session_factory() as db:
        row = FinanceRequest(user_id=user_id, request_id=request_id,
                             request_hash=fingerprint, status='running',
                             expires_at=utc_now() + timedelta(hours=24))
        row.lease_expires_at = utc_now() - timedelta(seconds=1)
        db.add(row)
        db.commit()
    def forbidden(*args, **kwargs):
        raise AssertionError('interrupted request repeated a paid model call')
    service = client.app.state.finance_service
    service.metered = SimpleNamespace(execute=forbidden)
    result = client.get(f'/api/v1/finance/requests/{request_id}', headers=headers)
    assert result.status_code == 200
    assert result.json()['status'] == 'failed'
    assert result.json()['error_code'] == 'finance_interrupted'
    replay = client.post('/api/v1/finance/ask', headers=headers, json=payload)
    assert replay.json() == result.json()
    import pytest

    from asset_based_agent.report_review_server.services.auth_service import (
        ServiceError,
    )
    with client.app.state.session_factory() as db:
        with pytest.raises(ServiceError):
            service._finish(db, user_id, request_id, {'status': 'succeeded'})
        assert db.get(FinanceRequest, (user_id, request_id)).status == 'failed'


def test_finance_cleanup_recovers_only_expired_execution_leases(client):
    from datetime import timedelta

    from asset_based_agent.report_review_server.finance_models import FinanceRequest
    from asset_based_agent.report_review_server.models import utc_now
    from asset_based_agent.report_review_server.services.temporary_data_cleanup import (
        cleanup_expired_temporary_data,
    )
    identity = login(client, 'admin', 'AdminPassword123!', instance='finance-cleanup')
    user_id, now = identity['user']['user_id'], utc_now()
    stale, live = uuid4().hex, uuid4().hex
    with client.app.state.session_factory() as db:
        for request_id, seconds in [(stale, -1), (live, 900)]:
            row = FinanceRequest(user_id=user_id, request_id=request_id,
                                 request_hash='fixture', status='running',
                                 expires_at=now + timedelta(hours=24))
            row.lease_expires_at = now + timedelta(seconds=seconds)
            db.add(row)
        db.commit()
        cleanup_expired_temporary_data(db, now=now)
        db.expire_all()
        assert db.get(FinanceRequest, (user_id, stale)).status == 'failed'
        assert db.get(FinanceRequest, (user_id, live)).status == 'running'


def test_finance_execution_checkpoint_renews_live_work_and_fences_expired_worker(client):
    from datetime import timedelta

    import pytest

    from asset_based_agent.report_review_server.finance_models import FinanceRequest
    from asset_based_agent.report_review_server.models import utc_now
    from asset_based_agent.report_review_server.services.auth_service import (
        ServiceError,
    )

    identity = login(client, 'admin', 'AdminPassword123!', instance='finance-checkpoint')
    user_id, request_id, now = identity['user']['user_id'], uuid4().hex, utc_now()
    service = client.app.state.finance_service
    with client.app.state.session_factory() as db:
        row = FinanceRequest(user_id=user_id, request_id=request_id, request_hash='fixture',
                             status='running', expires_at=now + timedelta(hours=24),
                             lease_expires_at=now + timedelta(seconds=60))
        db.add(row)
        db.commit()
        service._check_cancelled(db, user_id, request_id)
        assert row.lease_expires_at.replace(tzinfo=now.tzinfo) > now + timedelta(seconds=850)
        row.lease_expires_at = now - timedelta(seconds=1)
        db.commit()
        with pytest.raises(ServiceError) as error:
            service._check_cancelled(db, user_id, request_id)
        assert error.value.code == 'finance_interrupted'
        assert db.get(FinanceRequest, (user_id, request_id)).status == 'failed'
