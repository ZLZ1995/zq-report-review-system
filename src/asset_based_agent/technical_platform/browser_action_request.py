"""Native action binding. A valid model-shaped request never grants permission."""
from typing import Literal

from pydantic import Field, field_validator

from .browser_policy import credential_origin
from .execution_contracts import IdentityText, Positive, ScopedRecord


class BrowserActionRequest(ScopedRecord):
    revision: Positive
    claim_token: IdentityText
    environment: Literal['test', 'production']
    tab_id: IdentityText
    page_version: int = Field(ge=0, strict=True)
    origin: str = Field(max_length=2048)
    action: Literal['observe', 'navigate', 'click', 'fill', 'select', 'login', 'scroll', 'wait', 'download', 'upload']
    target: str = Field(min_length=1, max_length=256, pattern=r'^[A-Za-z0-9:_-]+$')
    payload_sha256: str = Field(pattern=r'^[0-9a-f]{64}$')

    @field_validator('origin')
    @classmethod
    def exact_origin(cls, value):
        if credential_origin(value) != value:
            raise ValueError('Canonical HTTPS origin required')
        return value
