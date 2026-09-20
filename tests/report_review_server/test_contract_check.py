"""K02：服务端源码级契约——/capabilities、OpenAPI 与契约检查一致。"""


def test_server_declares_material_evidence_and_openapi_contains_it(client):
    from asset_based_agent.report_review_server.contract_check import (
        check_capabilities_against_openapi,
    )
    response = client.get('/api/v1/capabilities')
    assert response.status_code == 200
    capabilities = response.json()
    assert capabilities['capabilities'].get('material_evidence') == 1
    openapi = client.get('/openapi.json').json()
    schemas = openapi['components']['schemas']
    assert 'MaterialEvidence' in schemas
    assert 'evidence' in schemas['EvidenceRef']['properties']
    assert check_capabilities_against_openapi(capabilities, openapi) == []


def test_contract_check_accepts_consistent_documents():
    from asset_based_agent.report_review_server.contract_check import (
        check_capabilities_against_openapi,
    )
    capabilities = {'schema_version': 1, 'protocol_version': 1,
                    'capabilities': {'task_understanding': 1, 'material_evidence': 1}}
    openapi = {'components': {'schemas': {
        'MaterialEvidence': {'type': 'object', 'properties': {'format': {}}},
        'EvidenceRef': {'type': 'object',
                        'properties': {'id': {}, 'name': {}, 'sha256': {}, 'evidence': {}}}}}}
    assert check_capabilities_against_openapi(capabilities, openapi) == []


def test_contract_check_flags_schema_without_capability_declaration():
    from asset_based_agent.report_review_server.contract_check import (
        check_capabilities_against_openapi,
    )
    capabilities = {'schema_version': 1, 'protocol_version': 1,
                    'capabilities': {'task_understanding': 1}}
    openapi = {'components': {'schemas': {
        'MaterialEvidence': {'type': 'object'},
        'EvidenceRef': {'type': 'object', 'properties': {'id': {}, 'evidence': {}}}}}}
    issues = check_capabilities_against_openapi(capabilities, openapi)
    assert any('未声明 material_evidence' in issue for issue in issues)
