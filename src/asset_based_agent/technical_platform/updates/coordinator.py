"""Verified preparation only. Installing staged content requires separate consent.

No sequence is committed here: a failed or cancelled download must not prevent a
retry. The installer must reverify signature, bytes, state and compatibility.
"""

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import httpx

from ..storage_layout import StorageLayout
from .downloader import download_and_stage
from .manifest import ReleaseManifest, UpdatePolicy, verify_manifest
from .trusted_keys import PUBLIC_KEYS, REVOKED_KEY_IDS


@dataclass(frozen=True)
class PreparedUpdate:
    manifest: ReleaseManifest
    directory: Path
    signed_manifest: bytes


def _client() -> httpx.Client:
    # No platform auth, browser cookies, .netrc auth or implicit proxy credentials.
    return httpx.Client(trust_env=False, timeout=30, follow_redirects=False)


def prepare_update(raw: bytes, *, layout: StorageLayout, policy: UpdatePolicy,
                   now: int, cancelled: Callable[[], bool] = lambda: False,
                   client_factory: Callable[[], httpx.Client] = _client) -> PreparedUpdate:
    release = verify_manifest(raw, keys=PUBLIC_KEYS, revoked_keys=REVOKED_KEY_IDS,
                              policy=policy, now=now)
    with client_factory() as client:
        directory = download_and_stage(release, layout=layout, client=client,
                                       allowed_hosts=policy.allowed_hosts, cancelled=cancelled)
    return PreparedUpdate(release, directory, raw)

