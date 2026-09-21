import sqlite3

import pytest

from asset_based_agent.technical_platform.storage_preferences import StoragePreferences


def vaults(tmp_path):
    from asset_based_agent.technical_platform.browser_credential_vault import (
        CredentialVault,
    )
    program, data = tmp_path/'program', tmp_path/'data'
    program.mkdir(); data.mkdir()
    prefs = StoragePreferences(tmp_path/'index.sqlite', program)
    prefs.select('alice', data); prefs.select('bob', data)
    return (CredentialVault(prefs, 'alice', environment='test'),
            CredentialVault(prefs, 'bob', environment='test'),
            CredentialVault(prefs, 'alice', environment='production'))


def save(vault, **kwargs):
    return vault.save('https://example.com/login', 'synthetic-user', 'synthetic-password',
                      confirmed=True, login_succeeded=True, **kwargs)


def test_vault_real_encryption_exact_origin_and_owner_isolation(tmp_path):
    vault, other, production = vaults(tmp_path)
    key = save(vault)
    assert [(v.key, v.username) for v in vault.entries()] == [(key, 'synthetic-user')]
    assert other.entries() == production.entries() == []
    login = vault._for_fill(key, 'https://example.com:443/page', authorized=True)
    assert login.password == 'synthetic-password'
    assert 'synthetic-password' not in repr(login)
    for url in ('https://evil.example.com', 'https://example.com:444', 'http://example.com'):
        with pytest.raises((ValueError, PermissionError)):
            vault._for_fill(key, url, authorized=True)
    with pytest.raises(PermissionError):
        vault._for_fill(key, 'https://example.com', authorized=False)
    for file in tmp_path.rglob('*'):
        if file.is_file():
            assert b'synthetic-password' not in file.read_bytes()
            assert b'synthetic-user' not in file.read_bytes()


def test_save_requires_consent_and_success_no_silent_update(tmp_path):
    vault, _, _ = vaults(tmp_path)
    for confirmed, success in ((False, True), (True, False)):
        with pytest.raises(PermissionError):
            vault.save('https://example.com', 'u', 'p', confirmed=confirmed, login_succeeded=success)
    key = save(vault)
    with pytest.raises(ValueError):
        save(vault)
    with pytest.raises(PermissionError):
        vault.save('https://example.com', 'synthetic-user', 'wrong', confirmed=True,
                   login_succeeded=False, replace_id=key)
    assert vault._for_fill(key, 'https://example.com', authorized=True).password == 'synthetic-password'
    vault.save('https://example.com', 'synthetic-user', 'updated', confirmed=True,
               login_succeeded=True, replace_id=key)
    assert vault._for_fill(key, 'https://example.com', authorized=True).password == 'updated'


def test_never_prompt_multi_account_and_delete(tmp_path):
    vault, _, _ = vaults(tmp_path)
    key = save(vault)
    vault.save('https://example.com', 'second', 'other', confirmed=True, login_succeeded=True)
    assert len(vault.entries()) == 2
    vault.set_prompt('https://example.com', 'never', confirmed=True)
    assert vault.prompt_policy('https://example.com/path') == 'never'
    with pytest.raises(PermissionError):
        save(vault, replace_id=key)
    vault.set_prompt('https://example.com', 'ask', confirmed=True)
    vault.delete(key, confirmed=True)
    assert [entry.username for entry in vault.entries()] == ['second']
    with pytest.raises(PermissionError):
        vault.delete(vault.entries()[0].key, confirmed=False)


def test_unknown_schema_and_ciphertext_copy_rejected(tmp_path):
    vault, other, _ = vaults(tmp_path)
    key = save(vault)
    other.entries()
    with sqlite3.connect(vault.path) as db:
        row = db.execute('SELECT * FROM credentials').fetchone()
    with sqlite3.connect(other.path) as db:
        db.execute('INSERT INTO credentials VALUES(?,?,?)', row)
    with pytest.raises(ValueError):
        other._for_fill(key, 'https://example.com', authorized=True)
    with sqlite3.connect(vault.path) as db:
        db.execute('PRAGMA user_version=999')
    with pytest.raises(ValueError):
        vault.entries()


def test_missing_data_root_is_not_recreated(tmp_path):
    vault, _, _ = vaults(tmp_path)
    save(vault)
    data = tmp_path/'data'
    data.rename(tmp_path/'offline')
    with pytest.raises((OSError, ValueError)):
        vault.entries()
    assert not data.exists()


def test_encryption_failure_preserves_previous_password(tmp_path, monkeypatch):
    from asset_based_agent.technical_platform import browser_credential_vault as module
    vault, _, _ = vaults(tmp_path)
    key = save(vault)
    def fail(*args):
        raise ValueError('Synthetic encryption unavailable')
    monkeypatch.setattr(module, 'protect', fail)
    with pytest.raises(ValueError):
        save(vault, replace_id=key)
    assert vault._for_fill(key, 'https://example.com', authorized=True).password == 'synthetic-password'
