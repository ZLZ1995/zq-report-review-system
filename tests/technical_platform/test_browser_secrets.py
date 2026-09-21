import pytest


def test_real_dpapi_roundtrip_and_context_binding():
    from asset_based_agent.technical_platform.browser_secrets import protect, unprotect
    payload = b'synthetic-test-secret-only'
    encrypted = protect(payload, b'account-a/site-a')
    assert payload not in encrypted
    assert unprotect(encrypted, b'account-a/site-a') == payload
    with pytest.raises(ValueError, match='credential protection'):
        unprotect(encrypted, b'account-b/site-a')
    with pytest.raises(ValueError, match='credential protection'):
        unprotect(encrypted[:-8]+b'tampered', b'account-a/site-a')


def test_dpapi_never_falls_back_to_plaintext(monkeypatch):
    import win32crypt

    from asset_based_agent.technical_platform.browser_secrets import protect
    def fail(*args):
        raise OSError('synthetic-secret-must-not-be-echoed')
    monkeypatch.setattr(win32crypt, 'CryptProtectData', fail)
    with pytest.raises(ValueError) as error:
        protect(b'secret', b'context')
    assert 'secret-must' not in str(error.value)
    assert error.value.__suppress_context__


def test_dpapi_flags_never_use_machine_scope(monkeypatch):
    import win32crypt

    from asset_based_agent.technical_platform.browser_secrets import protect
    original = win32crypt.CryptProtectData
    flags = []
    def capture(*args):
        flags.append(args[-1])
        return original(*args)
    monkeypatch.setattr(win32crypt, 'CryptProtectData', capture)
    protect(b'synthetic', b'context')
    assert flags == [1]
