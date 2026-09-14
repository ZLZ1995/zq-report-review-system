from __future__ import annotations

from pathlib import Path

import pytest

from asset_based_agent.report_review_app.domain.enums import FileRole, ProjectStatus
from asset_based_agent.report_review_app.repositories.project_repository import (
    ProjectRepository,
)
from asset_based_agent.report_review_app.services.file_service import (
    DuplicateSourceFileError,
    FileImportService,
    LegacyOfficeFormatError,
    UnsupportedFileTypeError,
    sha256_file,
)


def write_source(path: Path, content: bytes = b"content") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def test_import_files_copies_without_modifying_source_and_classifies_roles(
    tmp_path: Path,
) -> None:
    source_dir = tmp_path / "来源"
    report = write_source(source_dir / "某公司资产评估报告.docx", b"docx")
    workbook = write_source(source_dir / "市场法测算表.xlsx", b"xlsx")
    reference = write_source(source_dir / "审计报告.pdf", b"pdf")
    repository = ProjectRepository(tmp_path / "projects")
    project = repository.create("审核项目")
    service = FileImportService(repository)
    source_hashes = {path: sha256_file(path) for path in (report, workbook, reference)}

    imported = service.import_files(
        project,
        [report, workbook, reference],
        round_number=1,
    )

    assert [item.role for item in imported] == [
        FileRole.MAIN_REPORT,
        FileRole.CALCULATION_WORKBOOK,
        FileRole.REFERENCE_DOCUMENT,
    ]
    assert all(Path(item.original_path).is_file() for item in imported)
    assert all(sha256_file(path) == digest for path, digest in source_hashes.items())
    assert imported[2].ocr_status == "pending"
    assert repository.get(project.project_id).status == ProjectStatus.READY


@pytest.mark.parametrize("filename", ["legacy.doc", "legacy.xls"])
def test_legacy_office_files_require_user_conversion(
    tmp_path: Path,
    filename: str,
) -> None:
    repository = ProjectRepository(tmp_path / "projects")
    project = repository.create("project")
    source = write_source(tmp_path / filename)

    with pytest.raises(LegacyOfficeFormatError, match="converted by the user"):
        FileImportService(repository).import_files(project, [source], round_number=1)


def test_unsupported_file_type_is_rejected(tmp_path: Path) -> None:
    repository = ProjectRepository(tmp_path / "projects")
    project = repository.create("project")
    source = write_source(tmp_path / "notes.txt")

    with pytest.raises(UnsupportedFileTypeError, match="unsupported"):
        FileImportService(repository).import_files(project, [source], round_number=1)


def test_duplicate_file_in_same_round_is_rejected(tmp_path: Path) -> None:
    repository = ProjectRepository(tmp_path / "projects")
    project = repository.create("project")
    first = write_source(tmp_path / "one.docx", b"same")
    second = write_source(tmp_path / "two.docx", b"same")
    service = FileImportService(repository)
    service.import_files(project, [first], round_number=1)

    with pytest.raises(DuplicateSourceFileError, match="duplicate"):
        service.import_files(project, [second], round_number=1)


def test_role_override_is_respected(tmp_path: Path) -> None:
    repository = ProjectRepository(tmp_path / "projects")
    project = repository.create("project")
    source = write_source(tmp_path / "unknown.docx")
    resolved = source.resolve()

    imported = FileImportService(repository).import_files(
        project,
        [source],
        round_number=1,
        role_overrides={str(resolved): FileRole.VALUATION_EXPLANATION},
    )

    assert imported[0].role == FileRole.VALUATION_EXPLANATION


def test_replacement_mapping_is_persisted_for_next_round(tmp_path: Path) -> None:
    repository = ProjectRepository(tmp_path / "projects")
    project = repository.create("project")
    first = write_source(tmp_path / "round1.docx", b"one")
    first_import = FileImportService(repository).import_files(
        project,
        [first],
        round_number=1,
    )[0]
    second = write_source(tmp_path / "round2.docx", b"two")

    replacement = FileImportService(repository).import_files(
        project,
        [second],
        round_number=2,
        replacement_overrides={str(second.resolve()): first_import.file_id},
    )[0]

    assert replacement.replaces_file_id == first_import.file_id
