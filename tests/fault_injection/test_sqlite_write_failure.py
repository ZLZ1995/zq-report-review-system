"""S8-04 故障注入：SQLite 写失败（库被外部独占锁定）。

注入：另一连接持有 EXCLUSIVE 锁 → vault 写操作在 busy_timeout 与
重试耗尽后干净抛 sqlite3.OperationalError；锁释放后库内数据完好。
"""
from __future__ import annotations

import sqlite3

import pytest

import asset_based_agent.technical_platform.browser_credential_vault as vault_module
from asset_based_agent.technical_platform.browser_credential_vault import (
    CredentialVault,
)
from asset_based_agent.technical_platform.storage_preferences import (
    StoragePreferences,
)


def _vault(tmp_path):
    program, data = tmp_path / 'program', tmp_path / 'data'
    program.mkdir()
    data.mkdir()
    prefs = StoragePreferences(tmp_path / 'index.sqlite', program)
    prefs.select('alice', data)
    return CredentialVault(prefs, 'alice', environment='test')


def test_sqlite_write_failure_keeps_vault_intact(tmp_path, monkeypatch):
    vault = _vault(tmp_path)
    key = vault.save('https://example.com/login', 'saved-user',
                     'saved-password', confirmed=True, login_succeeded=True)
    # 缩短锁等待，保持测试快速
    monkeypatch.setattr(vault_module, '_BUSY_TIMEOUT_MS', 50)
    monkeypatch.setattr(vault_module, '_LOCK_RETRIES', 2)
    monkeypatch.setattr(vault_module, '_LOCK_RETRY_SLEEP', 0.01)

    locker = sqlite3.connect(vault.path)
    locker.execute('BEGIN EXCLUSIVE')
    locker.execute('UPDATE credentials SET origin = origin')
    try:
        with pytest.raises(sqlite3.OperationalError):
            vault.save('https://other.example.com/', 'x', 'y',
                       confirmed=True, login_succeeded=True)
    finally:
        locker.rollback()
        locker.close()

    # 锁释放后：原有数据完好，vault 恢复可写
    assert [entry.key for entry in vault.entries()] == [key]
    assert vault._for_fill(key, 'https://example.com/page',
                           authorized=True).password == 'saved-password'
    new_key = vault.save('https://other.example.com/', 'x', 'y',
                         confirmed=True, login_succeeded=True)
    assert new_key != key
