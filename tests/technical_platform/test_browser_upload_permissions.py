import pytest


def scope():
    from asset_based_agent.technical_platform.browser_upload_permissions import (
        UploadScope,
    )
    return UploadScope(identity={'owner': 'a', 'project_id': 'p', 'session_id': 's',
        'task_id': 't', 'request_id': 'r'}, environment='test', revision=1, step_id='upload',
        tab_id='tab', page_version=3, origin='https://example.com', object_label='Test project 001',
        field_id='file-1', receipt_id='receipt-1', claim_token='claim-1',
        artifact={'path': 'D:/test/synthetic.docx', 'name': 'synthetic.docx', 'size': 4,
                  'sha256': 'a' * 64, 'file_identity': 'b' * 64})


@pytest.mark.parametrize('field,value', [
    ('origin', 'https://other.test'), ('object_label', 'Other project'), ('tab_id', 'other'),
    ('page_version', 4), ('revision', 2), ('field_id', 'file-2'), ('receipt_id', 'other'),
    ('claim_token', 'other'), ('environment', 'production')])
def test_upload_permit_is_bound_and_consumed_on_mismatch(field, value):
    from asset_based_agent.technical_platform.browser_upload_permissions import (
        UploadPermissions,
    )
    service = UploadPermissions(); current = scope()
    permit = service.authorize(current, confirmed=True)
    assert not service.consume(permit, current.model_copy(update={field: value}), active=True)
    assert not service.consume(permit, current, active=True)


def test_upload_permit_requires_consent_expiry_and_active_context():
    from asset_based_agent.technical_platform.browser_upload_permissions import (
        UploadPermissions,
    )
    now = [0.0]; service = UploadPermissions(clock=lambda: now[0]); current = scope()
    with pytest.raises(PermissionError): service.authorize(current, confirmed=False)
    permit = service.authorize(current, confirmed=True)
    assert service.consume(permit, current, active=True)
    assert not service.consume(permit, current, active=True)
    permit = service.authorize(current, confirmed=True)
    assert not service.consume(permit, current, active=False)
    permit = service.authorize(current, confirmed=True)
    now[0] = 61
    assert not service.consume(permit, current, active=True)
    permit = service.authorize(current, confirmed=True)
    service.close()
    assert not service.consume(permit, current, active=True)
    with pytest.raises(PermissionError): service.authorize(current, confirmed=True)


def test_upload_rejects_changed_artifact_and_page_takeover():
    from asset_based_agent.technical_platform.browser_upload_permissions import (
        UploadPermissions,
    )
    service = UploadPermissions(); current = scope()
    permit = service.authorize(current, confirmed=True)
    changed = current.artifact.model_copy(update={'sha256': 'c' * 64})
    assert not service.consume(permit, current.model_copy(update={'artifact': changed}), active=True)
    permit = service.authorize(current, confirmed=True)
    service.revoke_tab(current.tab_id)
    assert not service.consume(permit, current, active=True)
    permit = service.authorize(current, confirmed=True)
    service.revoke_task(current.identity)
    assert not service.consume(permit, current, active=True)
