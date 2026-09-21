"""Bounded HTTPS download and isolated extraction; never switches live programs."""

import hashlib
import os
import re
import shutil
import stat
import tempfile
import zipfile
from collections.abc import Callable
from pathlib import Path
from urllib.parse import urljoin

import httpx

from ..storage_layout import StorageLayout
from .manifest import ReleaseManifest, validate_download_url

RESERVE_BYTES = 200 * 1024**2
MAX_EXPANDED_BYTES = 8 * 1024**3
MAX_MEMBERS = 20000


def _check_cancel(cancelled: Callable[[], bool]) -> None:
    if cancelled():
        raise InterruptedError('update cancelled; current version unchanged')


def _space(path: Path, required: int) -> None:
    if shutil.disk_usage(path).free < required + RESERVE_BYTES:
        raise OSError('insufficient update staging disk space')


def _members(package: zipfile.ZipFile) -> list[zipfile.ZipInfo]:
    members = package.infolist()
    if not members or len(members) > MAX_MEMBERS:
        raise ValueError('invalid archive member count')
    seen: dict[str, bool] = {}
    total = 0
    for member in members:
        name = member.filename
        parts = name.rstrip('/').split('/')
        mode = member.external_attr >> 16
        if (not name or name != member.orig_filename or '\\' in name or
                any(not p or p in ('.', '..') or p[-1:] in (' ', '.') or
                    any(ord(c) < 32 or c in '<>:"|?*' for c in p) or
                    re.fullmatch(r'(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?', p, re.IGNORECASE)
                    for p in parts) or member.flag_bits & 1 or
                stat.S_IFMT(mode) not in (0, stat.S_IFREG, stat.S_IFDIR)):
            raise ValueError('unsafe archive member')
        key = '/'.join(parts).casefold()
        if key in seen:
            raise ValueError('duplicate archive member')
        seen[key] = member.is_dir()
        total += member.file_size
        if (total > MAX_EXPANDED_BYTES or
                member.file_size > max(1, member.compress_size) * 1000):
            raise ValueError('archive expansion limit exceeded')
    for key in seen:
        parts = key.split('/')
        if any(seen.get('/'.join(parts[:i])) is False for i in range(1, len(parts))):
            raise ValueError('archive file/directory collision')
    return members


def download_and_stage(release: ReleaseManifest, *, layout: StorageLayout,
                       client: httpx.Client, allowed_hosts: frozenset[str],
                       cancelled: Callable[[], bool] = lambda: False) -> Path:
    """Caller must verify the signed manifest first; staged files remain inactive.

    Failed attempts are retained in a uniquely owned staging folder, not delivered
    as ready. No broad cleanup, program replacement, or user-data deletion occurs.
    HTTP credentials/cookies from the platform session must not be supplied here.
    """
    _check_cancel(cancelled)
    url = release.url
    validate_download_url(url, allowed_hosts)
    staging = layout.update_staging
    staging.mkdir(parents=True, exist_ok=True)
    _space(staging, release.size)
    attempt = Path(tempfile.mkdtemp(prefix='update-', dir=staging))
    partial = attempt / 'package.partial'
    hasher = hashlib.sha256()
    downloaded = 0
    for redirects in range(6):
        _check_cancel(cancelled)
        if (client.auth is not None or client.cookies or
                any(header in client.headers for header in ('authorization', 'cookie', 'proxy-authorization'))):
            raise ValueError('download client must not contain credentials')
        validate_download_url(url, allowed_hosts)
        with client.stream('GET', url, follow_redirects=False, timeout=30,
                           headers={'Accept-Encoding': 'identity'}) as response:
            if response.is_redirect:
                if redirects == 5 or not response.headers.get('location'):
                    raise ValueError('invalid release redirect chain')
                url = urljoin(url, response.headers['location'])
                continue
            response.raise_for_status()
            if response.status_code != 200 or response.headers.get('content-encoding', 'identity') != 'identity':
                raise ValueError('unsupported package response')
            length = response.headers.get('content-length')
            if length is not None and int(length) != release.size:
                raise ValueError('package length mismatch')
            with partial.open('xb') as output:
                for chunk in response.iter_bytes(chunk_size=64 * 1024):
                    _check_cancel(cancelled)
                    downloaded += len(chunk)
                    if downloaded > release.size:
                        raise ValueError('package size exceeded')
                    hasher.update(chunk)
                    output.write(chunk)
                output.flush()
                os.fsync(output.fileno())
            break
    if downloaded != release.size or hasher.hexdigest() != release.sha256:
        raise ValueError('package digest or size mismatch')
    _check_cancel(cancelled)
    with zipfile.ZipFile(partial) as package:
        members = _members(package)
        _space(attempt, sum(member.file_size for member in members))
        extracting = attempt / 'extracting'
        extracting.mkdir()
        for member in members:
            _check_cancel(cancelled)
            target = extracting.joinpath(*member.filename.rstrip('/').split('/'))
            if not target.resolve().is_relative_to(extracting.resolve()):
                raise ValueError('archive target escaped staging')
            if member.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with package.open(member) as source, target.open('xb') as output:
                while chunk := source.read(64 * 1024):
                    _check_cancel(cancelled)
                    output.write(chunk)
                output.flush()
                os.fsync(output.fileno())
    _check_cancel(cancelled)
    ready = attempt / 'ready'
    extracting.rename(ready)
    return ready

