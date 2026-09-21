"""S01 现状冻结：浏览器。

正确行为（必须通过）：三档模式的浏览器动作确认矩阵。
已知缺陷（xfail）：TLS-01 浏览器能力未暴露为标准 Agent Tool，Agent Loop 无法调用。
"""
import pytest


def test_browser_confirmation_matrix_per_mode():
    from asset_based_agent.technical_platform.agent_permission_modes import (
        requires_browser_confirmation,
    )
    assert requires_browser_confirmation('request', 'navigate')
    assert requires_browser_confirmation('request', 'upload')
    assert not requires_browser_confirmation('risk', 'navigate')
    assert requires_browser_confirmation('risk', 'upload')
    assert not requires_browser_confirmation('full', 'upload')


@pytest.mark.xfail(reason='TLS-01：浏览器能力未暴露为标准 Agent Tool', strict=True)
def test_browser_exposed_as_agent_tools():
    from asset_based_agent.technical_platform.tools import browser_tools
    assert hasattr(browser_tools, 'browser_open')
