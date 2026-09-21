import pytest


def test_builtin_contracts_match_real_adapters_and_keep_generation_boundaries():
    from asset_based_agent.technical_platform.skill_contracts import builtin_contracts
    from asset_based_agent.technical_platform.skills import (
        BUILTINS,
        DETAIL,
        HISTORY,
        REVIEW,
    )
    contracts = builtin_contracts()
    assert set(contracts) == {s.id for s in BUILTINS}
    assert contracts[DETAIL.id].required_roles == ['balance_sheet']
    assert 'trial_balance' in contracts[DETAIL.id].optional_roles
    assert contracts[HISTORY.id].source_extensions == ['.xlsx']
    assert '.pdf' not in contracts[HISTORY.id].source_extensions
    assert contracts[REVIEW.id].modify_originals is False
    assert all(c.modify_originals is False for c in contracts.values())


def test_unknown_fields_and_write_original_contract_are_rejected():
    from asset_based_agent.technical_platform.skill_contracts import (
        SkillContract,
        builtin_contracts,
    )
    base = next(iter(builtin_contracts().values())).model_dump()
    for change in ({'modify_originals': True}, {'shell_command': 'run'}, {'schema_version': True}):
        with pytest.raises(ValueError):
            SkillContract.model_validate({**base, **change})
