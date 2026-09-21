"""Qt browser port used by Agent browser tools.

The Agent worker never touches QWebEngine objects directly. Calls are marshalled
to the BrowserPanel GUI thread and return only bounded, non-secret values.
"""
from __future__ import annotations

import json


class QtBrowserAgentBackend:
    def __init__(self, panel, *, timeout=20.0):
        self.panel = panel
        self.timeout = timeout

    def _call(self, callback):
        return self.panel.dispatch_agent_call(callback, timeout=self.timeout)

    def open(self, url):
        self._call(lambda: self.panel.open_address(url))
        return {'url': url}

    def navigate(self, url):
        self._call(lambda: self.panel.open_address(url))
        return {'url': url}

    def observe(self):
        # The panel helper performs the asynchronous QWebEngine read on the
        # GUI thread and returns a bounded, non-secret snapshot.
        return self.panel.dispatch_agent_observe(timeout=self.timeout)

    def click(self, target):
        script = _target_script(target, action='click')
        return self.panel.dispatch_agent_javascript(script, timeout=self.timeout)

    def fill(self, target, text):
        script = _target_script(target, action='fill', value=text)
        return self.panel.dispatch_agent_javascript(script, timeout=self.timeout)

    def upload(self, _binding):
        raise RuntimeError('浏览器上传需要用户在文件选择器中完成接管')

    def download(self, target):
        self.click(target)
        raise RuntimeError('下载已触发；请从浏览器下载面板核对结果')

    def save_credential(self, _origin, _username, _password):
        raise RuntimeError('保存凭据必须由浏览器账号面板单独确认')

    def use_credential(self, _origin):
        raise RuntimeError('使用凭据必须由浏览器账号面板单独确认')

    def request_takeover(self, _reason):
        self.panel.dispatch_agent_takeover()
        return {'takeover': 'pending'}


def _target_script(target, *, action, value=''):
    target_json = json.dumps(str(target), ensure_ascii=False)
    value_json = json.dumps(str(value), ensure_ascii=False)
    if action == 'click':
        operation = 'node.click();'
    else:
        operation = (
            f'node.focus(); node.value={value_json}; '
            "node.dispatchEvent(new Event('input',{bubbles:true}));"
            "node.dispatchEvent(new Event('change',{bubbles:true}));"
        )
    return f"""(() => {{
      const target = {target_json};
      const nodes = [...document.querySelectorAll(
        'button,a,input,textarea,select,[role="button"]')];
      const node = nodes.find(n =>
        (n.innerText || n.value || n.getAttribute('aria-label') ||
         n.getAttribute('placeholder') || n.name || '').includes(target));
      if (!node) return {{ok:false, error:'未找到目标'}};
      {operation}
      return {{ok:true}};
    }})()"""
