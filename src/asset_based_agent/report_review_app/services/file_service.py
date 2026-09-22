"""Safe local import of user-selected review files."""

from __future__ import annotations

import hashlib
import os
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
        """事务化导入（S5-01）：预检查→staging→hash 校验→原子移动→manifest。

        任何环节失败都不留下孤儿正式文件；staging 目录总是清理。
        """
        if round_number < 1:
            raise ValueError("round_number must be at least 1")
        candidates = [path.resolve() for path in paths]
        if not candidates:
            raise ValueError("at least one file is required")
        # 1. 全部文件预检查
        for path in candidates:
            self._validate_source(path)
        overrides = role_overrides or {}
        replacements = replacement_overrides or {}
        known_file_ids = {item.file_id for item in project.files}
        # 2. 全部 replacement target 预验证（先验证，后复制）
        for source in candidates:
            replaces_file_id = replacements.get(str(source))
            if replaces_file_id and replaces_file_id not in known_file_ids:
                raise ValueError(
                    f"replacement target is not registered in project: {replaces_file_id}"
                )
        # 3. digest 全部计算 + 批次内/轮内重复检测
        known_hashes = {
            item.sha256 for item in project.files if item.round_number == round_number
        }
        digests: dict[Path, str] = {}
        for source in candidates:
            digest = sha256_file(source)
            if digest in known_hashes or digest in digests.values():
                raise DuplicateSourceFileError(
                    f"duplicate source file: {source.name}")
            digests[source] = digest

        project_dir = Path(project.project_path).resolve()
        files_root = project_dir / "files"
        destination_dir = files_root / f"round-{round_number:03d}" / "original"
        destination_dir.mkdir(parents=True, exist_ok=True)
        staging_dir = files_root / f".staging-{uuid.uuid4().hex}"

        staged: list[tuple[Path, Path, Path, str, str]] = []
        moved: list[Path] = []
        try:
            # 4. 复制到 staging + 5. staging hash 校验
            staging_dir.mkdir(parents=True)
            taken: set[str] = set()
            for source in candidates:
                digest = digests[source]
                file_id = f"FILE-{uuid.uuid4().hex.upper()}"
                destination = self._unique_destination(
                    destination_dir, source, file_id, taken=taken)
                taken.add(destination.name)
                staged_path = staging_dir / f"{file_id}{source.suffix.lower()}"
                shutil.copy2(source, staged_path)
                if sha256_file(staged_path) != digest:
                    raise OSError(
                        f"source copy verification failed: {source.name}")
                staged.append((staged_path, destination, source, digest,
                               file_id))
            # 6. 原子移动到正式目录（逐文件 os.replace；失败回滚已移动文件）
            for staged_path, destination, _source, _digest, _fid in staged:
                os.replace(staged_path, destination)
                moved.append(destination)
            # 7. 更新 manifest（失败时回滚已移动文件）
            imported: list[SourceFile] = []
            for _staged_path, destination, source, digest, file_id in staged:
                role = overrides.get(str(source)) or classify_file_role(source)
                imported.append(SourceFile(
                    file_id=file_id,
                    original_name=source.name,
                    extension=source.suffix.lower(),
                    sha256=digest,
                    size_bytes=source.stat().st_size,
                    role=role,
                    round_number=round_number,
                    original_path=str(destination),
                    replaces_file_id=replacements.get(str(source)),
                    extraction_status="pending",
                    ocr_status=("pending" if source.suffix.lower() == ".pdf"
                                else "not_required"),
                ))
            project.files.extend(imported)
            project.current_round = max(project.current_round, round_number)
            project.status = ProjectStatus.READY
            self.repository.save(project)
            return imported
        except BaseException:
            # 8. 失败回滚：删除已移动进正式目录的文件
            for path in moved:
                path.unlink(missing_ok=True)
            raise
        finally:
            shutil.rmtree(staging_dir, ignore_errors=True)

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
    def _unique_destination(directory: Path, source: Path, file_id: str,
                            *, taken: set[str]) -> Path:
        preferred = directory / source.name
        if preferred.name not in taken and not preferred.exists():
            return preferred
        candidate = directory / f"{source.stem}_{file_id[-8:]}{source.suffix}"
        while candidate.name in taken or candidate.exists():
            candidate = directory / (
                f"{source.stem}_{file_id[-8:]}_"
                f"{uuid.uuid4().hex[:6]}{source.suffix}")
        return candidate


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()
