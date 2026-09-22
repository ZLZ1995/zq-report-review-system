"""S8-04 故障注入：密文损坏（cipher error）。

注入：直接篡改 vault DB 中的 sealed 字节（磁盘损坏/异常写入场景）→
读取必须抛干净的 ValueError（业务可读的不可用信号），
不得崩溃为裸解密异常；vault 其余功能（写入新条目）保持可用。
"""
from __future__ import annotations

import sqlite3

import pytest

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


def test_tampered_sealed_bytes_raise_clean_value_error(tmp_path):
    vault = _vault(tmp_path)
    key = vault.save('https://example.com/login', 'saved-user',
                     'saved-password', confirmed=True, login_succeeded=True)
    # 篡改密文
    db = sqlite3.connect(vault.path)
    db.execute('UPDATE credentials SET sealed = ? WHERE key = ?',
               (b'tampered-garbage-bytes', key))
    db.commit()
    db.close()

    with pytest.raises(ValueError, match='unavailable'):
        vault.entries()
    with pytest.raises(ValueError, match='unavailable'):
        vault._for_fill(key, 'https://example.com/page', authorized=True)

    # 库结构未损坏：其余 origin 仍可正常读写
    new_key = vault.save('https://other.example.com/', 'a', 'b',
                         confirmed=True, login_succeeded=True)
    assert vault._for_fill(new_key, 'https://other.example.com/x',
                           authorized=True).password == 'b'
