"""Explicit, version-independent local data boundaries for browser and updates."""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

from .project_catalog import validate_business_directory


@dataclass(frozen=True)
class StorageLayout:
    program_root: Path
    data_root: Path
    owner: str

    def __post_init__(self):
        if not self.owner.strip():
            raise ValueError('Storage owner is required')
        program = self.program_root.resolve()
        data = validate_business_directory(self.data_root)
        if not program.is_dir():
            raise OSError('Program directory is unavailable')
        if data.is_relative_to(program) or program.is_relative_to(data):
            raise ValueError('Program and business data directories must be disjoint')
        object.__setattr__(self, 'program_root', program)
        object.__setattr__(self, 'data_root', data)

    def _path(self, name: str) -> Path:
        # Recheck each access: a missing removable disk must not be recreated.
        root = validate_business_directory(self.data_root)
        if root != self.data_root:
            raise ValueError('Data root changed through a link')
        account = sha256(self.owner.encode('utf-8')).hexdigest()
        target = root / '.zq-platform' / 'accounts' / account / name
        if target.resolve() != target:
            raise ValueError('Storage path redirects outside its approved account location')
        return target

    @property
    def cache(self) -> Path:
        return self._path('cache')

    @property
    def credentials(self) -> Path:
        return self._path('credentials')

    @property
    def browser_profiles(self) -> Path:
        return self._path('browser_profiles')

    @property
    def downloads(self) -> Path:
        return self._path('downloads')

    @property
    def update_staging(self) -> Path:
        return self._path('update_staging')

    def prepare(self) -> None:
        for name in ('cache', 'credentials', 'browser_profiles', 'downloads', 'update_staging'):
            self._path(name).mkdir(parents=True, exist_ok=True)
