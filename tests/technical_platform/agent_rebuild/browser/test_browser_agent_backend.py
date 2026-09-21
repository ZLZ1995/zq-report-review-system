from asset_based_agent.technical_platform.browser_agent_backend import (
    QtBrowserAgentBackend,
)


class Panel:
    def __init__(self):
        self.calls = []

    def open_address(self, url):
        self.calls.append(('open', url))

    def dispatch_agent_call(self, callback, *, timeout):
        self.calls.append(('call', timeout))
        return callback()

    def dispatch_agent_javascript(self, script, *, timeout):
        self.calls.append(('js', script, timeout))
        return {'ok': True}

    def dispatch_agent_observe(self, *, timeout):
        self.calls.append(('observe', timeout))
        return {'url': 'https://example.com', 'title': 'Example', 'content': 'ok'}

    def dispatch_agent_takeover(self):
        self.calls.append(('takeover',))


def test_qt_backend_marshals_navigation_observe_and_dom_actions():
    panel = Panel()
    backend = QtBrowserAgentBackend(panel, timeout=3)

    assert backend.open('https://example.com')['url'] == 'https://example.com'
    assert backend.navigate('https://example.com/a')['url'].endswith('/a')
    assert backend.observe()['content'] == 'ok'
    backend.click('登录')
    backend.fill('用户名', 'alice')

    assert [call[0] for call in panel.calls] == [
        'call', 'open', 'call', 'open', 'observe', 'js', 'js']
    assert 'alice' in panel.calls[-1][1]


def test_qt_backend_keeps_side_effects_explicitly_user_confirmed():
    panel = Panel()
    backend = QtBrowserAgentBackend(panel)

    try:
        backend.upload({'artifact_id': 'a'})
    except RuntimeError as exc:
        assert '接管' in str(exc)
    else:
        raise AssertionError('upload must not silently bypass GUI confirmation')
