"""Safe local import of user-selected review files."""

from __future__ import annotations

import hashlib
import shutil
import uuid
from collections.abc import Iterable
from pathlib import Path

from ..domain.enums import FileRole, ProjectStatus
from ..domain.models import AuditProject, SourceFile
from ..repositories.project_repository import ProjectRepository
from .file_role_service import classify_file_role

SUPPORTED_EXTENSIONS = {".docx", ".xlsx", ".xlsm", ".pdf"}
LEGACY_OFFICE_EXTENSIONS = {".doc", ".xls"}


class UnsupportedFileTypeError(ValueError):
    pass


class LegacyOfficeFormatError(UnsupportedFileTypeError):
    pass


class DuplicateSourceFileError(ValueError):
    pass


class FileImportService:
    def __init__(self, repository: ProjectRepository) -> None:
        self.repository = repository

    def import_files(
        self,
        project: AuditProject,
        paths: Iterable[Path],
        *,
        round_number: int,
        role_overrides: dict[str, FileRole] | None = None,
        replacement_overrides: dict[str, str] | None = None,
    ) -> list[SourceFile]:
        if round_number < 1:
            raise ValueError("round_number must be at least 1")
        candidates = [path.resolve() for path in paths]
        if not candidates:
            raise ValueError("at least one file is required")
        for path in candidates:
            self._validate_source(path)

        project_dir = Path(project.project_path).resolve()
        destination_dir = project_dir / "files" / f"round-{round_number:03d}" / "original"
        destination_dir.mkdir(parents=True, exist_ok=True)
        known_hashes = {
            item.sha256 for item in project.files if item.round_number == round_number
        }
        imported: list[SourceFile] = []
        overrides = role_overrides or {}
        replacements = replacement_overrides or {}
        known_file_ids = {item.file_id for item in project.files}

        for source in candidates:
            digest = sha256_file(source)
            if digest in known_hashes:
                raise DuplicateSourceFileError(f"duplicate source file: {source.name}")
            file_id = f"FILE-{uuid.uuid4().hex.upper()}"
            destination = self._unique_destination(destination_dir, source, file_id)
            shutil.copy2(source, destination)
            if sha256_file(destination) != digest:
                destination.unlink(missing_ok=True)
                raise OSError(f"source copy verification failed: {source.name}")
            role = overrides.get(str(source)) or classify_file_role(source)
            replaces_file_id = replacements.get(str(source))
            if replaces_file_id and replaces_file_id not in known_file_ids:
                raise ValueError(
                    f"replacement target is not registered in project: {replaces_file_id}"
                )
            item = SourceFile(
                file_id=file_id,
                original_name=source.name,
                extension=source.suffix.lower(),
                sha256=digest,
                size_bytes=source.stat().st_size,
                role=role,
                round_number=round_number,
                original_path=str(destination),
                replaces_file_id=replaces_file_id,
                extraction_status="pending",
                ocr_status="pending" if source.suffix.lower() == ".pdf" else "not_required",
            )
            imported.append(item)
            known_hashes.add(digest)

        project.files.extend(imported)
        project.current_round = max(project.current_round, round_number)
        project.status = ProjectStatus.READY
        self.repository.save(project)
        return imported

    @staticmethod
    def _validate_source(path: Path) -> None:
        if not path.is_file():
            raise FileNotFoundError(f"source file not found: {path}")
        suffix = path.suffix.lower()
        if suffix in LEGACY_OFFICE_EXTENSIONS:
            raise LegacyOfficeFormatError(
                f"legacy Office file must be converted by the user: {path.name}"
            )
        if suffix not in SUPPORTED_EXTENSIONS:
            raise UnsupportedFileTypeError(f"unsupported file type: {path.name}")

    @staticmethod
    def _unique_destination(directory: Path, source: Path, file_id: str) -> Path:
        preferred = directory / source.name
        if not preferred.exists():
            return preferred
        return directory / f"{source.stem}_{file_id[-8:]}{source.suffix}"


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()
