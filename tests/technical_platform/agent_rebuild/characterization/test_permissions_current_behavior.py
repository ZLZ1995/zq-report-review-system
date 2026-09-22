"""S01 现状冻结：权限模式。

正确行为（必须通过）：三档模式存在、未知模式被拒绝。
已知缺陷（xfail）：POL-01/POL-02 权限判断散落，缺少统一 PolicyEngine。
"""
import pytest


def test_three_permission_modes_exist_with_labels():
    from asset_based_agent.technical_platform.agent_permission_modes import (
        permission_mode_options,
    )
    assert [item.id for item in permission_mode_options()] == ['request', 'risk', 'full']
    assert [item.title for item in permission_mode_options()] == [
        '请求批准', '帮我批准', '范围内自动执行']


def test_unknown_permission_mode_rejected():
    from asset_based_agent.technical_platform.agent_permission_modes import (
        requires_confirmation,
    )
    with pytest.raises((ValueError, PermissionError)):
        requires_confirmation('everything', 'network')


@pytest.mark.xfail(reason='POL-01/POL-02：缺少统一 PolicyEngine，权限未成为所有 Tool 的共同输入', strict=True)
def test_unified_policy_engine_exists():
    from asset_based_agent.technical_platform.policies import engine
    assert hasattr(engine, 'PolicyEngine')
