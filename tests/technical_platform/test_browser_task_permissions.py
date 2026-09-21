from dataclasses import replace

import pytest

from asset_based_agent.technical_platform.execution_contracts import TaskIdentity


def scope():
    from asset_based_agent.technical_platform.browser_task_permissions import LoginScope
    return LoginScope(
        identity=TaskIdentity(owner='a', project_id='p', session_id='s', task_id='t', request_id='r'),
        environment='test', revision=1, step_id='login', tab_id='tab',
        page_version=3, origin='https://example.com', credential_id='account',
    )


def test_login_permission_requires_confirmation_and_is_single_use():
    from asset_based_agent.technical_platform.browser_task_permissions import (
        BrowserTaskPermissions,
    )
    service = BrowserTaskPermissions()
    current = scope()
    with pytest.raises(PermissionError):
        service.authorize_login(current, confirmed=False)
    permit = service.authorize_login(current, confirmed=True)
    assert service.consume_login(permit, current, task_active=True)
    assert not service.consume_login(permit, current, task_active=True)


@pytest.mark.parametrize('field,value', [
    ('environment', 'production'), ('revision', 2), ('step_id', 'upload'),
    ('tab_id', 'other'), ('page_version', 4), ('origin', 'https://other.test'),
    ('credential_id', 'other'),
])
def test_changed_login_scope_is_rejected_and_attempt_consumed(field, value):
    from asset_based_agent.technical_platform.browser_task_permissions import (
        BrowserTaskPermissions,
    )
    service = BrowserTaskPermissions()
    current = scope()
    permit = service.authorize_login(current, confirmed=True)
    assert not service.consume_login(permit, replace(current, **{field: value}), task_active=True)
    assert not service.consume_login(permit, current, task_active=True)


def test_cancel_takeover_forgery_and_timeout_reject():
    from asset_based_agent.technical_platform.browser_task_permissions import (
        BrowserTaskPermissions,
    )
    now = [10.0]
    service = BrowserTaskPermissions(clock=lambda: now[0])
    current = scope()
    permit = service.authorize_login(current, confirmed=True)
    assert not service.consume_login(replace(permit), current, task_active=True)
    service.revoke_tab('tab')
    assert not service.consume_login(permit, current, task_active=True)
    permit = service.authorize_login(current, confirmed=True)
    service.revoke_task(current.identity)
    assert not service.consume_login(permit, current, task_active=True)
    permit = service.authorize_login(current, confirmed=True)
    assert not service.consume_login(permit, current, task_active=False)
    permit = service.authorize_login(current, confirmed=True)
    now[0] += 61
    assert not service.consume_login(permit, current, task_active=True)


def test_other_identity_and_unsafe_origins_reject():
    from asset_based_agent.technical_platform.browser_task_permissions import (
        BrowserTaskPermissions,
    )
    service = BrowserTaskPermissions()
    current = scope()
    for field in ('owner', 'project_id', 'session_id', 'task_id', 'request_id'):
        permit = service.authorize_login(current, confirmed=True)
        other = current.identity.model_copy(update={field: 'other'})
        assert not service.consume_login(permit, replace(current, identity=other), task_active=True)
    for url in ('http://example.com', 'https://example.com/path', 'https://user:pass@example.com'):
        with pytest.raises(ValueError):
            replace(current, origin=url)


def test_closed_service_never_issues_or_accepts_permissions():
    from asset_based_agent.technical_platform.browser_task_permissions import (
        BrowserTaskPermissions,
    )
    service = BrowserTaskPermissions()
    current = scope()
    permit = service.authorize_login(current, confirmed=True)
    service.close()
    assert not service.consume_login(permit, current, task_active=True)
    with pytest.raises(PermissionError):
        service.authorize_login(current, confirmed=True)
