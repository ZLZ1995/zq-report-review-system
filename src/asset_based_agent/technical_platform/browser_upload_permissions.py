"""Native short-lived upload permits, additional to durable task authorization.

Not a model tool. The caller must independently verify the durable receipt,
staged file, exact native page/field, and active task before using the permit.
"""
import threading
import time
from dataclasses import dataclass
from typing import Literal
from uuid import uuid4

from pydantic import Field, field_validator

from .browser_download_artifacts import DownloadFingerprint
from .browser_policy import credential_origin
from .execution_contracts import IdentityText, Positive, ScopedRecord


class UploadScope(ScopedRecord):
    environment: Literal['test', 'production']
    revision: Positive
    claim_token: IdentityText
    tab_id: IdentityText
    page_version: int = Field(ge=0, strict=True)
    origin: str = Field(max_length=2048)
    object_label: str = Field(min_length=1, max_length=512)
    field_id: IdentityText
    target_key: str = Field(default='', pattern=r'^(?:[0-9a-f]{64})?$', strict=True)
    receipt_id: IdentityText
    artifact: DownloadFingerprint

    @field_validator('origin')
    @classmethod
    def exact_origin(cls, value):
        if credential_origin(value) != value:
            raise ValueError('Canonical HTTPS origin required')
        return value

    @field_validator('object_label')
    @classmethod
    def explicit_object(cls, value):
        if not value.strip() or any(ord(c) < 32 for c in value):
            raise ValueError('Explicit business object required')
        return value


@dataclass(frozen=True, repr=False)
class UploadPermit:
    key: str
    scope: UploadScope
    expires: float


class UploadPermissions:
    def __init__(self, *, clock=time.monotonic):
        self._clock = clock
        self._lock = threading.Lock()
        self._permits: dict[str, UploadPermit] = {}
        self._closed = False

    def authorize(self, scope: UploadScope, *, confirmed: bool) -> UploadPermit:
        if confirmed is not True or not isinstance(scope, UploadScope):
            raise PermissionError('Explicit native upload confirmation required')
        scope = UploadScope.model_validate(scope.model_dump())
        with self._lock:
            if self._closed:
                raise PermissionError('Upload permissions closed')
            now = self._clock()
            self._permits = {k: p for k, p in self._permits.items() if p.expires > now}
            if len(self._permits) >= 128:
                raise PermissionError('Too many pending upload confirmations')
            permit = UploadPermit(uuid4().hex, scope, now + 60)
            self._permits[permit.key] = permit
            return permit

    def consume(self, permit: UploadPermit, current: UploadScope, *, active: bool) -> bool:
        if not isinstance(permit, UploadPermit):
            return False
        with self._lock:
            saved = self._permits.pop(permit.key, None)
            return (not self._closed and saved is permit and active is True
                    and permit.scope == current and self._clock() < permit.expires)

    def revoke_tab(self, tab_id: str) -> None:
        with self._lock:
            self._permits = {k: p for k, p in self._permits.items() if p.scope.tab_id != tab_id}

    def revoke_task(self, identity) -> None:
        with self._lock:
            self._permits = {k: p for k, p in self._permits.items() if p.scope.identity != identity}

    def close(self) -> None:
        with self._lock:
            self._closed = True
            self._permits.clear()
