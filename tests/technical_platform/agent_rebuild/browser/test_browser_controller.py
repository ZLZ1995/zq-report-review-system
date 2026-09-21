# S12 浏览器面板控制器：用户主动打开/隐藏；可见性按 session 隔离。
from asset_based_agent.technical_platform.application.browser_controller import (
    BrowserController,
)


class FakePanelPort:
    def __init__(self):
        self.calls = []

    def show(self, session_id, url):
        self.calls.append(('show', session_id, url))

    def hide(self, session_id):
        self.calls.append(('hide', session_id))


def test_user_can_open_and_hide_browser():
    port = FakePanelPort()
    controller = BrowserController(port)
    vm = controller.open_browser('s1', 'https://example.com/')
    assert vm.visible is True
    assert vm.url == 'https://example.com/'
    assert ('show', 's1', 'https://example.com/') in port.calls
    vm = controller.hide_browser('s1')
    assert vm.visible is False
    assert ('hide', 's1') in port.calls


def test_open_without_url_keeps_blank_page():
    port = FakePanelPort()
    controller = BrowserController(port)
    vm = controller.open_browser('s1')
    assert vm.visible is True
    assert vm.url == 'about:blank'


def test_visibility_is_scoped_per_session():
    port = FakePanelPort()
    controller = BrowserController(port)
    controller.open_browser('s1', 'https://a.example.com/')
    assert controller.view('s1').visible is True
    other = controller.view('s2')
    assert other.visible is False
    assert other.url is None
    # 隐藏 s1 不影响后续新会话的默认状态
    controller.hide_browser('s1')
    assert controller.view('s1').visible is False


def test_hide_does_not_close_backend_session():
    # 隐藏只是面板不可见；不得调用任何关闭/结束任务语义，
    # 后台浏览器任务继续运行（端口协议只有 show/hide）。
    port = FakePanelPort()
    controller = BrowserController(port)
    controller.open_browser('s1', 'https://a.example.com/')
    controller.hide_browser('s1')
    verbs = {call[0] for call in port.calls}
    assert verbs == {'show', 'hide'}
