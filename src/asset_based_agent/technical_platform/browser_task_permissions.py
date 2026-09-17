"""Ephemeral login permits for trusted local callers, never a model-facing tool.

The caller must derive scope from native task/tab state and explicit user intent.
This is an additional gate, not a replacement for vault account consent, page
ownership or DOM validation. No permission survives process restart.
"""
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from uuid import uuid4

from .browser_policy import credential_origin
from .execution_contracts import TaskIdentity


@dataclass(frozen=True)
class LoginScope:
    identity: TaskIdentity
    environment: str
    revision: int
    step_id: str
    tab_id: str
    page_version: int
    origin: str
    credential_id: str

    def __post_init__(self):
        TaskIdentity.model_validate(self.identity.model_dump())
        if credential_origin(self.origin) != self.origin:
            raise ValueError('Exact canonical HTTPS origin required')
        if (type(self.revision) is not int or self.revision < 1
                or type(self.page_version) is not int or self.page_version < 0):
            raise ValueError('Invalid task or page version')
        if any(not isinstance(v, str) or not v or len(v) > 128 or any(c.isspace() for c in v)
               for v in (self.environment, self.step_id, self.tab_id, self.credential_id)):
            raise ValueError('Invalid login identity')


@dataclass(frozen=True, repr=False)
class LoginPermit:
    key: str
    scope: LoginScope
    expires: float


class BrowserTaskPermissions:
    def __init__(self, *, clock: Callable[[], float] = time.monotonic):
        self._clock = clock
        self._permits: dict[str, LoginPermit] = {}
        self._lock = threading.Lock()
        self._closed = False

    def authorize_login(self, scope: LoginScope, *, confirmed: bool) -> LoginPermit:
        """Trusted local consent entry point; never register as an Agent tool."""
        if confirmed is not True:
            raise PermissionError('Explicit login task authorization required')
        if not isinstance(scope, LoginScope):
            raise TypeError('Native login scope required')
        with self._lock:
            if self._closed:
                raise PermissionError('Browser task permissions closed')
            now = self._clock()
            self._permits = {key: p for key, p in self._permits.items() if p.expires > now}
            if len(self._permits) >= 128:
                raise PermissionError('Too many pending login permissions')
            permit = LoginPermit(uuid4().hex, scope, now + 60)
            self._permits[permit.key] = permit
            return permit

    def consume_login(self, permit: LoginPermit, current: LoginScope, *, task_active: bool) -> bool:
        """Consume before use; actual fill must recheck vault and native page."""
        if not isinstance(permit, LoginPermit):
            return False
        with self._lock:
            saved = self._permits.pop(permit.key, None)
            return (saved is permit and task_active is True and permit.scope == current
                    and self._clock() < permit.expires)

    def revoke_tab(self, tab_id: str) -> None:
        with self._lock:
            self._permits = {k: p for k, p in self._permits.items() if p.scope.tab_id != tab_id}

    def revoke_task(self, identity: TaskIdentity) -> None:
        with self._lock:
            self._permits = {k: p for k, p in self._permits.items() if p.scope.identity != identity}

    def close(self) -> None:
        with self._lock:
            self._closed = True
            self._permits.clear()
