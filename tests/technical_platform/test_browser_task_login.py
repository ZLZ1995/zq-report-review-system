from dataclasses import replace

import pytest

from asset_based_agent.technical_platform.browser_task_permissions import (
    BrowserTaskPermissions,
    LoginScope,
)
from asset_based_agent.technical_platform.browser_trusted_login import TrustedLogin
from asset_based_agent.technical_platform.execution_contracts import TaskIdentity
from tests.technical_platform.test_browser_trusted_login import probe, setup


def bound():
    old, page, session, uses = setup()
    old.close()
    permissions = BrowserTaskPermissions()
    current = [None]
    agent_uses = []
    def agent_read(*args):
        agent_uses.append(args)
        return old.vault._for_fill(*args)
    old.vault._for_agent_fill = agent_read
    bridge = TrustedLogin(session, page, old.vault, tab_id='tab',
                          task_permissions=permissions, task_scope=lambda: current[0])
    ticket = probe(bridge, page)
    current[0] = LoginScope(
        identity=TaskIdentity(owner='alice', project_id='p', session_id='s', task_id='t', request_id='r'),
        environment='test', revision=1, step_id='login', tab_id='tab',
        page_version=bridge.page_version, origin='https://example.com', credential_id='credential')
    return bridge, page, permissions, current, ticket, agent_uses, uses


def test_task_fill_consumes_permission_and_uses_agent_vault_gate():
    bridge, page, permissions, current, ticket, agent_uses, _ = bound()
    permit = permissions.authorize_login(current[0], confirmed=True)
    results = []
    bridge.fill_for_task(ticket, permit, callback=results.append)
    assert len(agent_uses) == 1
    page.calls[-1][2]('{"ok":true}')
    assert results == [True]
    bridge.fill_for_task(ticket, permit, callback=results.append)
    assert results == [True, False] and len(agent_uses) == 1


@pytest.mark.parametrize('change', ['cancel', 'owner', 'environment', 'tab', 'page', 'navigation', 'closed'])
def test_native_scope_change_prevents_secret_read(change):
    bridge, page, permissions, current, ticket, agent_uses, uses = bound()
    permit = permissions.authorize_login(current[0], confirmed=True)
    if change == 'cancel': current[0] = None
    elif change == 'owner': current[0] = replace(current[0], identity=current[0].identity.model_copy(update={'owner': 'bob'}))
    elif change == 'environment': current[0] = replace(current[0], environment='production')
    elif change == 'tab': current[0] = replace(current[0], tab_id='other')
    elif change == 'page': current[0] = replace(current[0], page_version=99)
    elif change == 'navigation': page.loadStarted.emit()
    else: bridge.close()
    results = []
    bridge.fill_for_task(ticket, permit, callback=results.append)
    assert results == [False] and not agent_uses and not uses


def test_site_permission_denial_is_generic_and_never_dispatches_fill():
    bridge, page, permissions, current, ticket, _, _ = bound()
    permit = permissions.authorize_login(current[0], confirmed=True)
    def denied(*args): raise PermissionError('do not expose this detail')
    bridge.vault._for_agent_fill = denied
    before = len(page.calls)
    results = []
    bridge.fill_for_task(ticket, permit, callback=results.append)
    assert results == [False] and len(page.calls) == before


def test_cancel_after_dispatch_does_not_report_task_success():
    bridge, page, permissions, current, ticket, _, _ = bound()
    permit = permissions.authorize_login(current[0], confirmed=True)
    results = []
    bridge.fill_for_task(ticket, permit, callback=results.append)
    current[0] = None
    page.calls[-1][2]('{"ok":true}')
    assert results == [False]
