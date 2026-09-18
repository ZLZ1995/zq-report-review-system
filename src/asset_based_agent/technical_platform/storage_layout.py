"""Explicit, version-independent local data boundaries for browser and updates."""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path


@dataclass(frozen=True)
class StorageLayout:
    program_root: Path
    data_root: Path
    owner: str

    def __post_init__(self):
        if not self.owner.strip():
            raise ValueError('Storage owner is required')
        program = self.program_root.resolve()
        data = self.data_root.resolve()
        if not program.is_dir():
            raise OSError('Program directory is unavailable')
        if not data.is_dir():
            raise OSError('Platform data directory is unavailable')
        object.__setattr__(self, 'program_root', program)
        object.__setattr__(self, 'data_root', data)

    def _path(self, name: str) -> Path:
        # Recheck each access: a missing removable disk must not be recreated.
        root = self.data_root.resolve()
        if not root.is_dir():
            raise OSError('Platform data directory is unavailable')
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
