"""Short-lived, local-only save candidate; never an Agent observation or DTO.

The trusted browser controller owns flow_id and must discard on logout, account
switch, failed login, or page-context invalidation. Redirects are not proof of
login success. Final persistence requires explicit local user confirmation.
Python cannot guarantee zeroization of temporary strings or process memory.
"""
import json
from collections.abc import Callable
from time import monotonic
from uuid import uuid4

from .browser_credential_vault import CredentialVault
from .browser_policy import credential_origin
from .browser_secrets import protect, unprotect


class PendingLogin:
    def __init__(self, vault: CredentialVault, url: str, username: str, password: str,
                 *, flow_id: str, clock: Callable[[], float] = monotonic):
        self._sealed = b''
        if (not isinstance(flow_id, str) or not flow_id or len(flow_id) > 128
                or not isinstance(username, str) or not username or len(username) > 2048
                or not isinstance(password, str) or not password or len(password) > 8192
                or '\x00' in username or '\x00' in password):
            raise ValueError('Invalid pending login')
        self._vault = vault
        self._owner, self._environment = vault.owner, vault.environment
        self._origin = credential_origin(url)
        self._flow = flow_id
        self._clock = clock
        self._expires = clock() + 120.0
        self._context = json.dumps(['pending-login', vault.owner, vault.environment,
                                    self._origin, flow_id, uuid4().hex]).encode('utf-8')
        self._sealed = protect(json.dumps([username, password], ensure_ascii=True).encode('utf-8'), self._context)

    def __repr__(self) -> str:
        return '<PendingLogin redacted>'

    def discard(self) -> None:
        """Release the encrypted candidate, not a claim of OS-level secure erase."""
        self._sealed = b''

    def save(self, page_url: str, *, flow_id: str, confirmed: bool,
             login_succeeded: bool, replace_id: str | None = None) -> str:
        sealed, self._sealed = self._sealed, b''
        if (not sealed or confirmed is not True or login_succeeded is not True
                or self._clock() >= self._expires or flow_id != self._flow
                or (self._vault.owner, self._vault.environment) != (self._owner, self._environment)):
            raise PermissionError('Pending login is unavailable or unconfirmed')
        try:
            origin = credential_origin(page_url)
        except ValueError:
            raise PermissionError('Pending login website changed') from None
        if origin != self._origin:
            raise PermissionError('Pending login website changed')
        try:
            data = json.loads(unprotect(sealed, self._context))
            if not isinstance(data, list) or len(data) != 2 or not all(isinstance(v, str) for v in data):
                raise ValueError('Invalid pending login payload')
        except (ValueError, TypeError, UnicodeError):
            raise ValueError('Pending login is unavailable') from None
        return self._vault.save(origin, data[0], data[1], confirmed=True,
                                login_succeeded=True, replace_id=replace_id)
