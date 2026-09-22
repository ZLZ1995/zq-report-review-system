"""S5-02 CredentialVault 并发修复：读写并发不得随机 database is locked（先红后绿）。

验收：两线程并发 entries+save、prompt_policy+set_prompt、
agent_accounts+set_agent_access。
"""
from __future__ import annotations

import threading

from test_browser_credential_vault import save, vaults

ROUNDS = 40


def _run_concurrent(reader, writer):
    errors = []

    def guarded(fn):
        def wrapper():
            try:
                fn()
            except Exception as exc:  # noqa: BLE001 - 汇集并发错误统一断言
                errors.append(exc)
        return wrapper

    threads = [threading.Thread(target=guarded(reader)),
               threading.Thread(target=guarded(writer))]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)
    assert all(not thread.is_alive() for thread in threads), '并发线程卡死'
    return errors


def test_entries_concurrent_with_save(tmp_path):
    vault, _other, _prod = vaults(tmp_path)
    save(vault)

    def reader():
        for _ in range(ROUNDS):
            vault.entries()

    def writer():
        for index in range(ROUNDS):
            vault.save('https://example.com/login', f'user-{index}', 'pw',
                       confirmed=True, login_succeeded=True)

    errors = _run_concurrent(reader, writer)
    assert not errors, f'并发访问不得报错: {errors!r}'


def test_prompt_policy_concurrent_with_set_prompt(tmp_path):
    vault, _other, _prod = vaults(tmp_path)
    save(vault)

    def reader():
        for _ in range(ROUNDS):
            assert vault.prompt_policy('https://example.com') in {
                'ask', 'never'}

    def writer():
        for index in range(ROUNDS):
            vault.set_prompt('https://example.com',
                             'never' if index % 2 else 'ask',
                             confirmed=True)

    errors = _run_concurrent(reader, writer)
    assert not errors, f'并发访问不得报错: {errors!r}'


def test_agent_accounts_concurrent_with_set_agent_access(tmp_path):
    vault, _other, _prod = vaults(tmp_path)
    key = save(vault)

    def reader():
        for _ in range(ROUNDS):
            vault.agent_accounts('https://example.com')

    def writer():
        for index in range(ROUNDS):
            vault.set_agent_access(key, bool(index % 2), confirmed=True)

    errors = _run_concurrent(reader, writer)
    assert not errors, f'并发访问不得报错: {errors!r}'


def test_no_database_locked_errors_under_mixed_load(tmp_path):
    """混合读写高压：任何错误都不得是 database is locked。"""
    vault, _other, _prod = vaults(tmp_path)
    key = save(vault)

    def reader():
        for _ in range(ROUNDS):
            vault.entries()
            vault.prompt_policy('https://example.com')
            vault.agent_accounts('https://example.com')
            vault.blocked_sites()

    def writer():
        for index in range(ROUNDS):
            vault.set_prompt('https://example.com', 'ask', confirmed=True)
            vault.set_agent_access(key, True, confirmed=True)

    errors = _run_concurrent(reader, writer)
    locked = [e for e in errors if 'locked' in str(e).lower()]
    assert not locked, f'不得随机 database is locked: {locked!r}'
    assert not errors, f'并发访问不得报错: {errors!r}'
