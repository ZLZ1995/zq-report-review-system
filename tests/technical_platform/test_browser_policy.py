import pytest


@pytest.mark.parametrize('url,main,allowed', [
    ('https://example.com/', True, True), ('about:blank', True, True),
    ('file:///D:/private.txt', False, False), ('file:///D:/private.txt', True, False),
    ('data:text/html,hello', True, False), ('javascript:alert(1)', False, False),
    ('data:image/png;base64,AAAA', False, True), ('blob:https://example.com/id', False, True),
    ('wss://example.com/socket', False, True), ('wss://example.com/socket', True, False),
    ('chrome://settings', False, False), ('https://u:p@example.com', False, False),
])
def test_browser_request_scheme_boundaries(url, main, allowed):
    from asset_based_agent.technical_platform.browser_policy import request_allowed
    assert request_allowed(url, main_frame=main) is allowed


@pytest.mark.parametrize('url, main, blocked', [
    ('file:///D:/secret.txt', False, True),
    ('https://example.com/app.js', False, False),
    ('data:text/html,unsafe', True, True),
])
def test_request_interceptor_applies_policy(url, main, blocked):
    from PySide6.QtCore import QUrl
    from PySide6.QtWebEngineCore import QWebEngineUrlRequestInfo

    from asset_based_agent.technical_platform.browser_page import (
        BrowserRequestInterceptor,
    )

    class Request:
        denied = False

        def resourceType(self):
            return (QWebEngineUrlRequestInfo.ResourceType.ResourceTypeMainFrame if main
                    else QWebEngineUrlRequestInfo.ResourceType.ResourceTypeScript)

        def requestUrl(self):
            return QUrl(url)

        def block(self, value):
            self.denied = value

    request = Request()
    BrowserRequestInterceptor().interceptRequest(request)
    assert request.denied is blocked


@pytest.mark.parametrize('url', ['https://example.com/a?q=1#x', 'http://127.0.0.1:8080/',
                                 'https://zhongqinoa01.com/', 'about:blank'])
def test_manual_browser_accepts_general_web_urls(url):
    from asset_based_agent.technical_platform.browser_policy import navigation_url
    assert navigation_url(url).isValid()


@pytest.mark.parametrize('url', ['file:///D:/secret.txt', 'javascript:alert(1)', 'data:text/html,test',
    'chrome://settings', 'https://user:password@example.com', 'https://@example.com',
    'https://example.com\\@evil.test', 'https://example.com\n', 'about:config', 'https:///'])
def test_browser_rejects_host_resources_credential_urls_and_ambiguous_navigation(url):
    from asset_based_agent.technical_platform.browser_policy import navigation_url
    with pytest.raises(ValueError):
        navigation_url(url)


def test_saved_login_origin_requires_https_and_preserves_port_boundary():
    from asset_based_agent.technical_platform.browser_policy import credential_origin
    assert credential_origin('https://EXAMPLE.com:443/login?q=1') == 'https://example.com'
    assert credential_origin('https://example.com:8443/login') == 'https://example.com:8443'
    for url in ('http://example.com', 'about:blank', 'https://example.com@evil.test'):
        with pytest.raises(ValueError):
            credential_origin(url)


@pytest.mark.parametrize('address, expected', [
    ('https://[::1]:8443/login', 'https://[::1]:8443'),
    ('https://例子.测试/login', 'https://xn--fsqu00a.xn--0zwm56d'),
])
def test_credential_origin_canonical_host(address, expected):
    from asset_based_agent.technical_platform.browser_policy import credential_origin
    assert credential_origin(address) == expected


@pytest.mark.parametrize('url', ['https://example.com:99999', 'https://example.com:0',
                                 'https://example.com/%zz', 'https://user%40example.com'])
def test_malformed_host_port_and_escape_rejected(url):
    from asset_based_agent.technical_platform.browser_policy import navigation_url
    with pytest.raises(ValueError):
        navigation_url(url)


def test_normal_runtime_flags_allowed():
    from asset_based_agent.technical_platform.browser_policy import (
        check_runtime_environment,
    )
    check_runtime_environment({})
    check_runtime_environment({'QTWEBENGINE_CHROMIUM_FLAGS': '--lang=zh-CN'})


@pytest.mark.parametrize('environment', [
    {'QTWEBENGINE_DISABLE_SANDBOX': '1'},
    {'QTWEBENGINE_CHROMIUM_FLAGS': '--no-sandbox'},
    {'QTWEBENGINE_CHROMIUM_FLAGS': '--ignore-certificate-errors'},
    {'QTWEBENGINE_CHROMIUM_FLAGS': '--disable-web-security'},
    {'QTWEBENGINE_REMOTE_DEBUGGING': '9222'},
])
def test_browser_refuses_insecure_runtime_environment(environment):
    from asset_based_agent.technical_platform.browser_policy import (
        check_runtime_environment,
    )
    with pytest.raises(ValueError):
        check_runtime_environment(environment)
