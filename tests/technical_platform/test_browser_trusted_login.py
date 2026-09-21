import json
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QUrl


class Event:
    def __init__(self): self.handlers = []
    def connect(self, handler): self.handlers.append(handler)
    def disconnect(self, handler): self.handlers.remove(handler)
    def emit(self, *args):
        for handler in self.handlers: handler(*args)


class Page:
    def __init__(self):
        self.loadStarted, self.urlChanged, self.renderProcessTerminated = Event(), Event(), Event()
        self.calls = []
    def url(self): return QUrl('https://example.com/login')
    def isLoading(self): return False
    def runJavaScript(self, script, world, callback): self.calls.append((script, world, callback))


def setup():
    from asset_based_agent.technical_platform.browser_trusted_login import TrustedLogin
    page = Page()
    preferences = object()
    session = SimpleNamespace(owns_page=lambda candidate: candidate is page,
                              owner='alice', environment='test', preferences=preferences)
    uses = []
    def read(*args, **kwargs):
        uses.append(args)
        return SimpleNamespace(username='synthetic-user', password='synthetic-password')
    bridge = TrustedLogin(session, page, SimpleNamespace(_for_fill=read, owner='alice',
                                                        environment='test', preferences=preferences))
    return bridge, page, session, uses


def probe(bridge, page):
    result = []
    bridge.probe(result.append)
    script, world, callback = page.calls[-1]
    assert world == 1
    nonce = json.loads(script.rsplit(')(', 1)[1][:-1])
    callback(json.dumps({'ok': True, 'origin': 'https://example.com',
                         'action': 'https://example.com/login', 'nonce': nonce}))
    assert result[0] is not None
    return result[0]


def test_trusted_fill_one_use_and_no_secret_return():
    bridge, page, _, uses = setup()
    ticket = probe(bridge, page)
    result = []
    bridge.fill(ticket, 'credential', confirmed=True, callback=result.append)
    assert len(uses) == 1
    page.calls[-1][2]('{"ok":true}')
    assert result == [True]
    bridge.fill(ticket, 'credential', confirmed=True, callback=result.append)
    assert result == [True, False] and len(uses) == 1


def test_navigation_close_and_no_consent_never_decrypt():
    bridge, page, session, uses = setup()
    ticket = probe(bridge, page)
    result = []
    bridge.fill(ticket, 'credential', confirmed=False, callback=result.append)
    assert result == [False] and not uses
    ticket = probe(bridge, page)
    page.loadStarted.emit()
    bridge.fill(ticket, 'credential', confirmed=True, callback=result.append)
    assert not uses and result[-1] is False
    ticket = probe(bridge, page)
    session.owns_page = lambda candidate: False
    bridge.fill(ticket, 'credential', confirmed=True, callback=result.append)
    assert not uses and result[-1] is False


def test_late_probe_after_navigation_does_not_issue_ticket():
    bridge, page, _, uses = setup()
    result = []
    bridge.probe(result.append)
    script, _, callback = page.calls[-1]
    nonce = json.loads(script.rsplit(')(', 1)[1][:-1])
    page.urlChanged.emit(QUrl('https://example.com/next'))
    callback(json.dumps({'ok': True, 'origin': 'https://example.com',
                         'action': 'https://example.com/login', 'nonce': nonce}))
    assert result == [None] and not uses


def test_wrong_account_vault_cannot_bind_page():
    from asset_based_agent.technical_platform.browser_trusted_login import TrustedLogin
    _, page, session, _ = setup()
    with pytest.raises(ValueError):
        TrustedLogin(session, page, SimpleNamespace(owner='bob', environment='test',
                                                    preferences=session.preferences))


def test_expired_or_missing_ticket_never_decrypts(monkeypatch):
    from asset_based_agent.technical_platform import browser_trusted_login as module
    bridge, page, _, uses = setup()
    result = []
    bridge.fill(None, 'credential', confirmed=True, callback=result.append)
    ticket = probe(bridge, page)
    monkeypatch.setattr(module.time, 'monotonic', lambda: ticket.expires+1)
    bridge.fill(ticket, 'credential', confirmed=True, callback=result.append)
    assert result == [False, False] and not uses


def test_loading_page_does_not_issue_ticket():
    bridge, page, _, uses = setup()
    page.isLoading = lambda: True
    result = []
    bridge.probe(result.append)
    assert result == [None] and not page.calls and not uses


def test_close_disconnects_and_prevents_later_use():
    bridge, page, _, uses = setup()
    ticket = probe(bridge, page)
    bridge.close(); bridge.close()
    assert not page.loadStarted.handlers and not page.urlChanged.handlers
    result = []
    bridge.fill(ticket, 'credential', confirmed=True, callback=result.append)
    assert result == [False] and not uses
