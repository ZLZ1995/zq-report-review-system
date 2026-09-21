from asset_based_agent.technical_platform.agent_core.runtime import AgentKernel
from asset_based_agent.technical_platform.agent_core.cancellation import CancelToken


def test_kernel_cancel_open_tokens_is_synchronous():
    kernel = AgentKernel(repo=object(), model=None)
    token = CancelToken()
    kernel._cancels['op-1'] = token
    assert kernel.cancel_open(('op-1',)) == ['op-1']
    assert token.cancelled
