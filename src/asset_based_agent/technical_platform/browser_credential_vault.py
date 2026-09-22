"""Local-only website credentials. Not an Agent tool or a server DTO.

UI/trusted-fill code must supply real consent and verified page context. Boolean
arguments here are defensive checks, not substitutes for Harness authorization.

并发规则（S5-02）：纯读走普通读事务；写走 BEGIN IMMEDIATE；连接带
busy_timeout，短暂锁冲突有限重试——不再 timeout=0 一刀切。
"""
import json
import sqlite3
import stat
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

from .browser_policy import credential_origin
from .browser_secrets import protect, unprotect
from .storage_preferences import StoragePreferences

_BUSY_TIMEOUT_MS = 5000
_LOCK_RETRIES = 3
_LOCK_RETRY_SLEEP = 0.05


@dataclass(frozen=True)
class CredentialSummary:
    key: str
    origin: str
    username: str
    agent_allowed: bool = False
    version: str = ''


@dataclass(frozen=True)
class AgentAccount:
    key: str
    origin: str
    label: str


@dataclass(frozen=True, repr=False)
class LocalLogin:
    username: str = field(repr=False)
    password: str = field(repr=False)

    def __repr__(self):
        return '<LocalLogin redacted>'


class CredentialVault:
    def __init__(self, preferences: StoragePreferences, owner: str, *, environment: str = 'production'):
        if environment not in {'test', 'production'}:
            raise ValueError('Invalid credential environment')
        self.preferences, self.owner, self.environment = preferences, owner, environment

    @property
    def path(self) -> Path:
        with self.preferences.use(self.owner) as layout:
            return layout.credentials / f'{self.environment}.sqlite'

    @contextmanager
    def _database(self, *, write: bool = False):
        with self.preferences.use(self.owner) as layout:
            directory = layout.credentials
            directory.mkdir(parents=True, exist_ok=True)
            path = directory / f'{self.environment}.sqlite'
            for item in (path, Path(str(path)+'-journal'), Path(str(path)+'-wal'), Path(str(path)+'-shm')):
                resolved = item.resolve()
                # 并发下 WAL/journal 可能处于 delete-pending（回收中）：
                # resolve() 会返回 NT 内部 $Extend\$Deleted 路径，属无害瞬态，跳过
                if '$Deleted' in resolved.parts:
                    continue
                # resolve() 对已存在文件可能返回 \\?\ 扩展长度前缀形式，
                # 与词法路径仅前缀不同，规范化后再比较
                resolved_str = str(resolved)
                if resolved_str.startswith('\\\\?\\UNC\\'):
                    resolved = Path('\\\\' + resolved_str[8:])
                elif resolved_str.startswith('\\\\?\\'):
                    resolved = Path(resolved_str[4:])
                if resolved != item or item.is_symlink():
                    raise ValueError('Credential storage path is unsafe')
                try:
                    item_stat = item.stat()
                except FileNotFoundError:
                    continue  # 并发下 WAL/journal 文件可能刚被回收
                if not stat.S_ISREG(item_stat.st_mode) or item_stat.st_nlink != 1:
                    raise ValueError('Credential storage path is unsafe')
            db = sqlite3.connect(path, timeout=_BUSY_TIMEOUT_MS / 1000)
            try:
                db.execute('PRAGMA foreign_keys=ON')
                db.execute(f'PRAGMA busy_timeout={_BUSY_TIMEOUT_MS}')
                db.execute('PRAGMA journal_mode=WAL')
                write = self._open(db, write=write)
                yield db
                if write:
                    db.commit()
            except BaseException:
                db.rollback()
                raise
            finally:
                db.close()

    @staticmethod
    def _open(db: sqlite3.Connection, *, write: bool) -> bool:
        """打开事务并完成 schema 引导；返回最终是否为写事务。

        写请求与未初始化库的读请求都会升级为 BEGIN IMMEDIATE；
        短暂锁冲突按 _LOCK_RETRIES 重试。
        """
        attempts = _LOCK_RETRIES
        while True:
            try:
                version = db.execute('PRAGMA user_version').fetchone()[0]
                if version not in (0, 1, 2):
                    raise ValueError('Unknown credential schema')
                if write or version != 2:
                    db.execute('BEGIN IMMEDIATE')
                    write = True
                    db.execute('PRAGMA secure_delete=ON')
                    db.execute('CREATE TABLE IF NOT EXISTS credentials '
                               '(key TEXT PRIMARY KEY, origin TEXT NOT NULL, sealed BLOB NOT NULL)')
                    db.execute('CREATE TABLE IF NOT EXISTS prompts (origin TEXT PRIMARY KEY, policy TEXT NOT NULL)')
                    db.execute('CREATE TABLE IF NOT EXISTS agent_access '
                               '(key TEXT PRIMARY KEY REFERENCES credentials(key) ON DELETE CASCADE, sealed BLOB NOT NULL)')
                    db.execute('PRAGMA user_version=2')
                return write
            except sqlite3.OperationalError as exc:
                if 'locked' in str(exc).lower() and attempts > 1:
                    attempts -= 1
                    db.rollback()
                    time.sleep(_LOCK_RETRY_SLEEP)
                    continue
                raise

    def _context(self, key: str, origin: str) -> bytes:
        return json.dumps([self.owner, self.environment, origin, key], ensure_ascii=True).encode('utf-8')

    def _decode(self, key: str, origin: str, sealed: bytes) -> LocalLogin:
        try:
            data = json.loads(unprotect(sealed, self._context(key, origin)))
            if (not isinstance(data, dict) or set(data) != {'username', 'password'}
                    or not isinstance(data['username'], str) or not isinstance(data['password'], str)):
                raise ValueError('Invalid credential payload')
            return LocalLogin(data['username'], data['password'])
        except (ValueError, TypeError, UnicodeError):
            raise ValueError('Saved website credential is unavailable') from None

    def entries(self) -> list[CredentialSummary]:
        with self._database(write=False) as db:
            return [CredentialSummary(key, origin, self._decode(key, origin, sealed).username,
                                      self._agent_allowed(db, key, origin, sealed), sha256(sealed).hexdigest())
                    for key, origin, sealed in db.execute('SELECT key,origin,sealed FROM credentials ORDER BY origin,key')]

    def save(self, url: str, username: str, password: str, *, confirmed: bool,
             login_succeeded: bool, replace_id: str | None = None) -> str:
        if confirmed is not True or login_succeeded is not True:
            raise PermissionError('Successful login and explicit save consent required')
        origin = credential_origin(url)
        if (not username or len(username) > 2048 or not password or len(password) > 8192
                or '\x00' in username or '\x00' in password):
            raise ValueError('Invalid credential fields')
        with self._database(write=True) as db:
            row = db.execute('SELECT policy FROM prompts WHERE origin=?', (origin,)).fetchone()
            if row and row[0] == 'never':
                raise PermissionError('Saving disabled for this website')
            rows = db.execute('SELECT key,origin,sealed FROM credentials WHERE origin=?', (origin,)).fetchall()
            if replace_id is not None and replace_id not in {row[0] for row in rows}:
                raise ValueError('Credential replacement target missing')
            for key, site, sealed in rows:
                if key != replace_id and self._decode(key, site, sealed).username == username:
                    raise ValueError('Existing account requires explicit replacement')
            key = replace_id or uuid4().hex
            sealed = protect(json.dumps({'username': username, 'password': password}, ensure_ascii=True).encode('utf-8'),
                             self._context(key, origin))
            db.execute('INSERT INTO credentials VALUES(?,?,?) ON CONFLICT(key) DO UPDATE SET sealed=excluded.sealed',
                       (key, origin, sealed))
            # Replacing a password/account is not a renewed Agent-use consent.
            db.execute('DELETE FROM agent_access WHERE key=?', (key,))
            return key

    def _agent_allowed(self, db, key: str, origin: str, credential: bytes) -> bool:
        row = db.execute('SELECT sealed FROM agent_access WHERE key=?', (key,)).fetchone()
        if row is None:
            return False
        try:
            expected = sha256(credential).digest()
            return unprotect(row[0], self._context('agent-access:' + key, origin)) == expected
        except (ValueError, TypeError):
            return False

    def set_agent_access(self, key: str, allowed: bool, *, confirmed: bool, expected_version: str | None = None) -> None:
        """Trusted local settings UI only. Never register this as an Agent tool."""
        if confirmed is not True:
            raise PermissionError('Agent access requires explicit local confirmation')
        if not isinstance(allowed, bool):
            raise TypeError('Invalid Agent access setting')
        with self._database(write=True) as db:
            row = db.execute('SELECT origin,sealed FROM credentials WHERE key=?', (key,)).fetchone()
            if row is None:
                raise ValueError('Credential missing')
            if expected_version is not None and sha256(row[1]).hexdigest() != expected_version:
                raise ValueError('Credential changed since confirmation')
            if allowed:
                # Validate the credential before granting, but do not export it.
                self._decode(key, row[0], row[1])
                sealed = protect(sha256(row[1]).digest(), self._context('agent-access:' + key, row[0]))
                db.execute('INSERT INTO agent_access VALUES(?,?) '
                           'ON CONFLICT(key) DO UPDATE SET sealed=excluded.sealed', (key, sealed))
            else:
                db.execute('DELETE FROM agent_access WHERE key=?', (key,))

    def agent_accounts(self, url: str) -> list[AgentAccount]:
        """Only already-authorized references; callers still enforce task scope."""
        origin = credential_origin(url)
        with self._database(write=False) as db:
            accounts = []
            for key, sealed in db.execute('SELECT key,sealed FROM credentials WHERE origin=? ORDER BY key', (origin,)):
                if self._agent_allowed(db, key, origin, sealed):
                    username = self._decode(key, origin, sealed).username
                    visible = ''.join(c for c in username if c.isprintable())
                    label = (visible[:1] if visible else '') + '***'
                    accounts.append(AgentAccount(key, origin, label))
            return accounts

    def _for_agent_fill(self, key: str, page_url: str) -> LocalLogin:
        """Trusted caller only; task/tab authority must ALSO be checked by Harness."""
        origin = credential_origin(page_url)
        with self._database(write=False) as db:
            row = db.execute('SELECT sealed FROM credentials WHERE key=? AND origin=?', (key, origin)).fetchone()
            if row is None or not self._agent_allowed(db, key, origin, row[0]):
                raise PermissionError('Agent use is not authorized for this website account')
            return self._decode(key, origin, row[0])

    def _for_fill(self, key: str, page_url: str, *, authorized: bool) -> LocalLogin:
        """Trusted local caller only; never serialize the return value to a model."""
        if authorized is not True:
            raise PermissionError('Credential use requires authorization')
        origin = credential_origin(page_url)
        with self._database(write=False) as db:
            row = db.execute('SELECT sealed FROM credentials WHERE key=? AND origin=?', (key, origin)).fetchone()
            if row is None:
                raise PermissionError('Credential does not match the website')
            return self._decode(key, origin, row[0])

    def delete(self, key: str, *, confirmed: bool) -> None:
        if confirmed is not True:
            raise PermissionError('Credential deletion requires confirmation')
        with self._database(write=True) as db:
            db.execute('DELETE FROM credentials WHERE key=?', (key,))

    def set_prompt(self, url: str, policy: str, *, confirmed: bool) -> None:
        if confirmed is not True:
            raise PermissionError('Prompt policy requires confirmation')
        if policy not in {'ask', 'never'}:
            raise ValueError('Unknown prompt policy')
        origin = credential_origin(url)
        with self._database(write=True) as db:
            db.execute('INSERT INTO prompts VALUES(?,?) ON CONFLICT(origin) DO UPDATE SET policy=excluded.policy',
                       (origin, policy))

    def prompt_policy(self, url: str) -> str:
        origin = credential_origin(url)
        with self._database(write=False) as db:
            row = db.execute('SELECT policy FROM prompts WHERE origin=?', (origin,)).fetchone()
            return row[0] if row else 'ask'

    def blocked_sites(self) -> list[str]:
        with self._database(write=False) as db:
            return [credential_origin(row[0]) for row in db.execute(
                "SELECT origin FROM prompts WHERE policy='never' ORDER BY origin")]
