"""Reverify original signed package bytes at the offline installation boundary."""

import hashlib
import os
import zipfile
from collections.abc import Callable
from pathlib import Path

from ..project_catalog import validate_business_directory
from .downloader import _check_cancel, _members, _space
from .manifest import ReleaseManifest


def extract_verified_package(package: Path, release: ReleaseManifest, destination: Path,
                             *, cancelled: Callable[[], bool] = lambda: False) -> Path:
    if not destination.is_absolute() or destination.resolve() != destination:
        raise ValueError('Explicit installation destination required')
    validate_business_directory(destination.parent)
    if destination.exists():
        raise FileExistsError('Installed version directories cannot be overwritten')
    if not package.is_absolute() or package.resolve() != package:
        raise ValueError('Explicit non-redirected package required')
    # Hold one handle for hashing and extraction so a path swap cannot substitute
    # another archive between these two operations.
    with package.open('rb') as source:
        hasher = hashlib.sha256()
        size = 0
        while chunk := source.read(1024 * 1024):
            _check_cancel(cancelled)
            size += len(chunk)
            if size > release.size:
                raise ValueError('Package size changed')
            hasher.update(chunk)
        if size != release.size or hasher.hexdigest() != release.sha256:
            raise ValueError('Package signature digest mismatch')
        source.seek(0)
        with zipfile.ZipFile(source) as archive:
            members = _members(archive)
            _space(destination.parent, sum(member.file_size for member in members))
            destination.mkdir()
            for member in members:
                _check_cancel(cancelled)
                target = destination.joinpath(*member.filename.rstrip('/').split('/'))
                if target.resolve() != target or not target.is_relative_to(destination):
                    raise ValueError('Installation path redirected')
                if member.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(member) as archived, target.open('xb') as output:
                    while chunk := archived.read(65536):
                        _check_cancel(cancelled)
                        output.write(chunk)
                    output.flush()
                    os.fsync(output.fileno())
    _check_cancel(cancelled)
    return destination

