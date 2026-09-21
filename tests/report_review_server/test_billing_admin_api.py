from .conftest import bearer, login
from .test_billing_reconciliation import setup_unknown


def test_admin_reconciliation_api_is_scoped_and_idempotent(client):
    _, hold, _ = setup_unknown(client)
    headers = bearer(login(client, 'admin', 'AdminPassword123!', instance='billing')['access_token'])
    result = client.get('/api/v1/admin/billing-holds', headers=headers)
    assert result.status_code == 200
    assert result.json()['items'][0]['hold_id'] == hold
    assert 'ciphertext' not in result.text and 'api_key' not in result.text
    assert 'payload' not in result.text
    path = f'/api/v1/admin/billing-holds/{hold}/reconciliation'
    payload = {'confirmed_amount': '0.12', 'evidence_sha256': 'a'*64,
               'evidence_reference': 'SUPPORT-001'}
    first = client.post(path, headers=headers, json=payload)
    assert first.status_code == 200
    assert client.post(path, headers=headers, json=payload).json() == first.json()
    assert client.get(path, headers=headers).json() == first.json()
    assert client.get('/api/v1/admin/billing-holds', headers=headers).json()['items'] == []
    assert client.post(path, headers=headers, json={**payload, 'confirmed_amount': '0.13'}).status_code == 409
    assert client.post(path, headers=headers, json={**payload, 'admin_user_id': 'forged'}).status_code == 422


def test_customer_cannot_read_or_write_billing_reconciliation(client):
    _, hold, _ = setup_unknown(client)
    admin = bearer(login(client, 'admin', 'AdminPassword123!', instance='admin')['access_token'])
    client.post('/api/v1/admin/users', headers=admin, json={'username': 'customer',
        'display_name': 'test', 'temporary_password': '12345678'})
    user = bearer(login(client, 'customer', '12345678', instance='user')['access_token'])
    path = f'/api/v1/admin/billing-holds/{hold}/reconciliation'
    body = {'confirmed_amount': '0', 'evidence_sha256': 'a'*64, 'evidence_reference': 'TEST'}
    for headers, status in [({}, 401), (user, 403)]:
        assert client.get('/api/v1/admin/billing-holds', headers=headers).status_code == status
        assert client.get(path, headers=headers).status_code == status
        assert client.post(path, headers=headers, json=body).status_code == status


def test_admin_billing_contract_rejects_invalid_inputs_without_echo(client):
    _, hold, _ = setup_unknown(client)
    headers = bearer(login(client, 'admin', 'AdminPassword123!', instance='billing')['access_token'])
    path = f'/api/v1/admin/billing-holds/{hold}/reconciliation'
    body = {'confirmed_amount': '0', 'evidence_sha256': 'a'*64, 'evidence_reference': 'TEST'}
    for change in [{'confirmed_amount': 'NaN'}, {'confirmed_amount': '-1'},
                   {'confirmed_amount': '0.000000001'}, {'evidence_reference': 'secret/key'},
                   {'evidence_sha256': 'secret-key'}]:
        response = client.post(path, headers=headers, json={**body, **change})
        assert response.status_code == 422
        assert 'secret' not in response.text
    assert client.get('/api/v1/admin/billing-holds?limit=101', headers=headers).status_code == 422
    assert client.get('/api/v1/admin/billing-holds?offset=-1', headers=headers).status_code == 422
    assert client.get(path, headers=headers).status_code == 404
    assert client.get('/api/v1/admin/billing-holds', headers=headers).json()['items'][0]['status'] == 'uncertain'
