import sqlite3

import pytest

from tests.technical_platform.test_browser_credential_vault import save, vaults


def test_agent_access_is_explicit_scoped_and_revocable(tmp_path):
    vault, other, production = vaults(tmp_path)
    key = save(vault)
    assert vault.agent_accounts('https://example.com') == []
    with pytest.raises(PermissionError):
        vault._for_agent_fill(key, 'https://example.com')
    with pytest.raises(PermissionError):
        vault.set_agent_access(key, True, confirmed=False)
    vault.set_agent_access(key, True, confirmed=True)
    accounts = vault.agent_accounts('https://example.com/path')
    assert len(accounts) == 1 and accounts[0].key == key
    assert 'synthetic-user' not in repr(accounts)
    assert 'synthetic-password' not in repr(accounts)
    assert vault._for_agent_fill(key, 'https://example.com').password == 'synthetic-password'
    assert other.agent_accounts('https://example.com') == production.agent_accounts('https://example.com') == []
    for url in ('https://example.com.evil.test', 'https://example.com:444', 'http://example.com'):
        with pytest.raises((PermissionError, ValueError)):
            vault._for_agent_fill(key, url)
    vault.set_agent_access(key, False, confirmed=True)
    assert vault.agent_accounts('https://example.com') == []
    with pytest.raises(PermissionError):
        vault._for_agent_fill(key, 'https://example.com')
    assert vault._for_fill(key, 'https://example.com', authorized=True).password == 'synthetic-password'


def test_password_update_deletion_and_ciphertext_change_revoke_agent_use(tmp_path):
    vault, _, _ = vaults(tmp_path)
    key = save(vault)
    vault.set_agent_access(key, True, confirmed=True)
    save(vault, replace_id=key)
    assert not vault.agent_accounts('https://example.com')
    vault.set_agent_access(key, True, confirmed=True)
    vault.delete(key, confirmed=True)
    with sqlite3.connect(vault.path) as db:
        assert db.execute('SELECT count(*) FROM agent_access').fetchone()[0] == 0
    key = save(vault)
    assert not vault.agent_accounts('https://example.com')


def test_grant_copy_and_unknown_account_fail_closed(tmp_path):
    vault, other, _ = vaults(tmp_path)
    key = save(vault)
    vault.set_agent_access(key, True, confirmed=True)
    other.entries()
    with sqlite3.connect(vault.path) as db:
        credential = db.execute('SELECT * FROM credentials').fetchone()
        grant = db.execute('SELECT * FROM agent_access').fetchone()
    with sqlite3.connect(other.path) as db:
        db.execute('INSERT INTO credentials VALUES(?,?,?)', credential)
        db.execute('INSERT INTO agent_access VALUES(?,?)', grant)
    with pytest.raises((ValueError, PermissionError)):
        other._for_agent_fill(key, 'https://example.com')
    with pytest.raises(ValueError):
        vault.set_agent_access('missing', True, confirmed=True)


def test_legacy_database_migration_keeps_credentials_without_grant(tmp_path):
    vault, _, _ = vaults(tmp_path)
    key = save(vault)
    with sqlite3.connect(vault.path) as db:
        before = db.execute('SELECT * FROM credentials').fetchall()
        db.execute('DROP TABLE IF EXISTS agent_access')
        db.execute('PRAGMA user_version=1')
    assert not vault.agent_accounts('https://example.com')
    assert vault._for_fill(key, 'https://example.com', authorized=True).password == 'synthetic-password'
    with sqlite3.connect(vault.path) as db:
        assert db.execute('SELECT * FROM credentials').fetchall() == before
        assert db.execute('PRAGMA user_version').fetchone()[0] == 2


def test_stale_confirmation_cannot_authorize_replaced_password(tmp_path):
    vault, _, _ = vaults(tmp_path)
    key = save(vault)
    version = vault.entries()[0].version
    save(vault, replace_id=key)
    with pytest.raises(ValueError):
        vault.set_agent_access(key, True, confirmed=True, expected_version=version)
    assert not vault.agent_accounts('https://example.com')


def test_damaged_grant_and_invalid_toggle_never_allow_agent(tmp_path):
    vault, _, _ = vaults(tmp_path)
    key = save(vault)
    with pytest.raises(TypeError):
        vault.set_agent_access(key, 1, confirmed=True)
    vault.set_agent_access(key, True, confirmed=True)
    with sqlite3.connect(vault.path) as db:
        db.execute('UPDATE agent_access SET sealed=? WHERE key=?', (b'broken', key))
    assert vault.agent_accounts('https://example.com') == []
    with pytest.raises(PermissionError):
        vault._for_agent_fill(key, 'https://example.com')
