from types import SimpleNamespace

import pytest


@pytest.mark.parametrize('state,verified', [('succeeded', True), ('failed', True), ('cancelled', False)])
def test_download_feedback_distinguishes_user_confirmation_from_website_writes(state, verified):
    from asset_based_agent.technical_platform.app import PlatformWindow
    messages = []
    window = SimpleNamespace(append_output=lambda text, **kwargs: messages.append(text))
    target = SimpleNamespace(store=SimpleNamespace(run=lambda _: {'state': state}),
                             binding=SimpleNamespace(task_id='task'))
    result = {'verified': verified, 'verification': {'method': 'user_confirmed_download'},
              'summary': 'requested file', 'evidence': 'website text'}
    text = PlatformWindow.show_browser_result(window, result, target)
    if state == 'succeeded':
        assert '完整性校验' in text
        assert '由你确认' in text
        assert '不表示网站写入成功' in text
    else:
        assert '完整性校验' not in text
    assert messages == [text]
