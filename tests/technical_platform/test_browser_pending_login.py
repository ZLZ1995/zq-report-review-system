import pytest

from tests.technical_platform.test_browser_credential_vault import vaults


def candidate(vault, clock, **kwargs):
    from asset_based_agent.technical_platform.browser_pending_login import PendingLogin
    return PendingLogin(vault, 'https://example.com/login', 'user', 'secret-test',
                        flow_id='native-flow-1', clock=lambda: clock[0], **kwargs)


def approve(pending, **kwargs):
    return pending.save('https://example.com/home', flow_id='native-flow-1',
                        confirmed=True, login_succeeded=True, **kwargs)


def test_candidate_is_memory_only_until_explicit_success_and_consent(tmp_path):
    vault, _, _ = vaults(tmp_path)
    clock = [0.0]
    pending = candidate(vault, clock)
    assert not vault.path.exists()
    assert 'secret-test' not in repr(pending)
    assert b'secret-test' not in pending._sealed
    key = approve(pending)
    assert pending._sealed == b''
    assert vault._for_fill(key, 'https://example.com', authorized=True).password == 'secret-test'
    with pytest.raises(PermissionError):
        approve(pending)


@pytest.mark.parametrize('reason', ['cancel', 'failed', 'no-consent', 'expired', 'site', 'flow'])
def test_rejected_candidate_is_consumed_without_saving(tmp_path, reason):
    vault, _, _ = vaults(tmp_path)
    clock = [0.0]
    pending = candidate(vault, clock)
    url, flow, confirmed, success = 'https://example.com', 'native-flow-1', True, True
    if reason == 'cancel':
        pending.discard()
    elif reason == 'failed':
        success = False
    elif reason == 'no-consent':
        confirmed = False
    elif reason == 'expired':
        clock[0] = 120.0
    elif reason == 'site':
        url = 'https://other.example.com'
    else:
        flow = 'native-flow-2'
    with pytest.raises(PermissionError):
        pending.save(url, flow_id=flow, confirmed=confirmed, login_succeeded=success)
    assert pending._sealed == b''
    assert not vault.path.exists()
    with pytest.raises(PermissionError):
        approve(pending)


def test_update_is_explicit_and_never_policy_is_respected(tmp_path):
    vault, _, _ = vaults(tmp_path)
    clock = [0.0]
    key = vault.save('https://example.com', 'user', 'old', confirmed=True, login_succeeded=True)
    with pytest.raises(ValueError):
        approve(candidate(vault, clock))
    assert vault._for_fill(key, 'https://example.com', authorized=True).password == 'old'
    assert approve(candidate(vault, clock), replace_id=key) == key
    vault.set_prompt('https://example.com', 'never', confirmed=True)
    with pytest.raises(PermissionError):
        approve(candidate(vault, clock), replace_id=key)


def test_encryption_failure_and_invalid_context_never_save(tmp_path, monkeypatch):
    from asset_based_agent.technical_platform import browser_pending_login as module
    vault, _, _ = vaults(tmp_path)
    def fail(*args):
        raise ValueError('Synthetic protection failure')
    monkeypatch.setattr(module, 'protect', fail)
    with pytest.raises(ValueError):
        candidate(vault, [0.0])
    assert not vault.path.exists()


def test_tampered_candidate_is_consumed_and_old_record_preserved(tmp_path):
    vault, _, _ = vaults(tmp_path)
    key = vault.save('https://example.com', 'user', 'old', confirmed=True, login_succeeded=True)
    pending = candidate(vault, [0.0])
    pending._sealed = b'broken'
    with pytest.raises(ValueError):
        approve(pending, replace_id=key)
    assert pending._sealed == b''
    assert vault._for_fill(key, 'https://example.com', authorized=True).password == 'old'
