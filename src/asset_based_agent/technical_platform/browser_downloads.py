"""Download staging: incomplete data is never published or used to overwrite files."""
import os
import tempfile
from pathlib import Path

from .project_catalog import validate_business_directory


def validate_filename(name: str) -> str:
    reserved = {'CON', 'PRN', 'AUX', 'NUL', 'CONIN$', 'CONOUT$'}
    reserved.update(f'{prefix}{index}' for prefix in ('COM', 'LPT') for index in '123456789¹²³')
    if (not name or len(name) > 180 or name[-1:] in {' ', '.'}
            or any(ord(c) < 32 or c in '<>:"/\\|?*' for c in name)
            or name.split('.')[0].upper() in reserved):
        raise ValueError('Unsafe download filename')
    return name


class DownloadTarget:
    def __init__(self, destination: Path):
        self.destination = destination
        self._validate_destination()
        self.stage = Path(tempfile.mkdtemp(prefix='.zq-download-', dir=destination.parent))
        self.partial = self.stage / 'payload.part'
        self.cleanup_pending = False

    def _validate_destination(self) -> None:
        destination = self.destination
        if not destination.is_absolute() or destination.resolve() != destination:
            raise ValueError('Download destination must be absolute and not redirected')
        validate_business_directory(destination.parent)
        validate_filename(destination.name)
        if destination.exists():
            raise FileExistsError('Download destination already exists')

    def _validate_stage(self) -> None:
        if (self.stage.resolve() != self.stage or not self.stage.is_dir()
                or self.partial.resolve() != self.partial):
            raise ValueError('Download staging path changed')

    def publish(self) -> Path:
        self._validate_destination()
        self._validate_stage()
        if not self.partial.is_file() or self.partial.stat().st_nlink != 1:
            raise ValueError('Download payload is missing or linked')
        # Atomic no-clobber publication on the same volume. On unsupported
        # filesystems retain staging and fail; never fall back to overwrite.
        os.link(self.partial, self.destination)
        try:
            self.partial.unlink()
            self.stage.rmdir()
        except OSError:
            # Publication already succeeded. Cleanup debt is a separate state,
            # not grounds to retry the download or touch the completed file.
            self.cleanup_pending = True
        return self.destination

    def discard(self) -> None:
        self._validate_stage()
        for candidate in (self.partial, self.stage / 'payload.part.crdownload'):
            if candidate.resolve() != candidate or candidate.is_symlink():
                raise ValueError('Download staging content redirected')
            if candidate.is_file():
                candidate.unlink()
        # Unknown entries are intentionally retained, not recursively deleted.
        self.stage.rmdir()
