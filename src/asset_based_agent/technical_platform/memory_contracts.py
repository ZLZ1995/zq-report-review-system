"""Versioned, provenance-labelled memory records.

Memory is context only.  It never grants file, browser, model, or write permission.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

MemoryScope = Literal["user", "project", "session"]
MemoryKind = Literal["preference", "fact", "instruction"]
MemorySource = Literal["explicit_user", "verified_artifact"]
MemoryStatus = Literal["active", "revoked"]


@dataclass(frozen=True)
class MemoryRecord:
    id: str
    owner: str
    scope: MemoryScope
    key: str
    text: str
    kind: MemoryKind
    source: MemorySource
    source_ref: str | None
    status: MemoryStatus
    priority: int
    project_id: str | None
    session_id: str | None
    valid_until: datetime | None
    version: int
    created: datetime
    updated: datetime
