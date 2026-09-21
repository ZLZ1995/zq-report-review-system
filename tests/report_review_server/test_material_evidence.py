"""K03 server: material evidence capability and compat contract parity."""


def test_capabilities_advertise_material_evidence(client):
    data = client.get('/api/v1/capabilities').json()
    assert data['capabilities']['material_evidence'] == 1


def test_compat_contract_accepts_bounded_evidence():
    from asset_based_agent.report_review_server import compat_agent_contracts as compat
    ref = compat.EvidenceRef.model_validate({
        'id': 'f1', 'name': 'a.xls', 'sha256': 'a' * 64,
        'evidence': {'format': 'xls', 'readable': True,
                     'document_type': 'trial_balance', 'entity_name': 'A8T',
                     'period_start': None, 'period_end': '2026-07-31',
                     'sheet_names': ['Sheet0'], 'header_evidence': ['科目汇总试算表'],
                     'confidence': 0.9, 'warnings': []}})
    assert ref.evidence.entity_name == 'A8T'


def test_compat_contract_rejects_legacy_unknown_keys_and_keeps_old_payloads():
    import pytest
    from pydantic import ValidationError

    from asset_based_agent.report_review_server import compat_agent_contracts as compat
    ref = compat.EvidenceRef.model_validate({'id': 'f1', 'name': 'a.xlsx', 'sha256': 'b' * 64})
    assert ref.evidence is None
    with pytest.raises(ValidationError):
        compat.EvidenceRef.model_validate({'id': 'f1', 'name': 'a.xls', 'sha256': 'a' * 64,
                                           'evidence': {'format': 'xls', 'path': '/secret'}})
