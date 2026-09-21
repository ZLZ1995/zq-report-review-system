def test_understanding_catalog_describes_inputs_outputs_and_limits():
    from asset_based_agent.technical_platform.capability_registry import (
        planning_candidates,
    )
    rows = {r['id']: r for r in planning_candidates()}
    detail = rows['valuation-detail-workbook-fill']['description']
    assert 'balance_sheet' in detail and 'trial_balance' in detail
    assert '不修改原件' in detail and '.xlsx' in detail
    assert 'Office' in detail or 'WPS' in detail
    assert len(detail) <= 1000


def test_missing_locked_template_is_not_advertised_as_ready(monkeypatch):
    from asset_based_agent.technical_platform import generation
    from asset_based_agent.technical_platform.capability_registry import (
        planning_candidates,
    )
    def unavailable(skill_id):
        raise ValueError('private path must not leak')
    monkeypatch.setattr(generation, 'locked_template', unavailable)
    rows = planning_candidates()
    assert {r['id'] for r in rows} == {'report.review', 'review.preflight'}
    assert 'private' not in str(rows)
