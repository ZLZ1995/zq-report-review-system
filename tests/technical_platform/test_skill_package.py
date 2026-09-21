import hashlib
import json
import zipfile

import pytest

from asset_based_agent.technical_platform.skill_package import inspect_package


def package(tmp_path, *, update=None, entries=None):
    rules = b"Review visible evidence only."
    manifest = {
        "schema_version": 1, "id": "example.review", "version": "1.0.0",
        "name": "Example review", "adapter": "report.review",
        "capabilities": ["read_selected_files", "generate_artifacts"],
        "dependencies": {"python-docx": ">=1.0,<2"},
        "files": {"SKILL.md": hashlib.sha256(rules).hexdigest()},
    }
    if update:
        manifest.update(update)
    path = tmp_path / "sample.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("manifest.json", json.dumps(manifest))
        archive.writestr("SKILL.md", rules)
        for name, data in (entries or {}).items():
            archive.writestr(name, data)
    return path


def test_valid_package_reports_metadata_and_missing_dependencies(tmp_path):
    result = inspect_package(package(tmp_path), installed_versions={})
    assert result.manifest["id"] == "example.review"
    assert result.instructions == "Review visible evidence only."
    assert result.missing_dependencies == ("python-docx>=1.0,<2",)
    assert len(result.sha256) == 64
    assert not result.ready
    assert inspect_package(package(tmp_path), installed_versions={"python-docx": "1.2.0"}).ready


@pytest.mark.parametrize("name", ["../escape.txt", "/absolute.txt", "C:/escape.txt", "a\\b.txt", "plugin.py"])
def test_unsafe_or_undeclared_entries_rejected_without_extraction(tmp_path, name):
    with pytest.raises(ValueError):
        inspect_package(package(tmp_path, entries={name: "bad"}), installed_versions={})
    assert not (tmp_path / "escape.txt").exists()


@pytest.mark.parametrize("update", [
    {"id": "../escape"}, {"version": "latest"}, {"adapter": "shell"},
    {"capabilities": ["modify_originals"]}, {"schema_version": 2},
    {"dependencies": {"package @ https://example.com/x": ""}},
    {"files": {"SKILL.md": "0" * 64}},
])
def test_invalid_contract_or_integrity_rejected(tmp_path, update):
    with pytest.raises(ValueError):
        inspect_package(package(tmp_path, update=update), installed_versions={})


def test_dependency_version_mismatch_disables_package(tmp_path):
    result = inspect_package(package(tmp_path), installed_versions={"python-docx": "0.8.11"})
    assert not result.ready


def test_symlink_entry_rejected(tmp_path):
    path = package(tmp_path)
    with zipfile.ZipFile(path, "a") as archive:
        entry = zipfile.ZipInfo("link.md")
        entry.create_system = 3
        entry.external_attr = 0o120777 << 16
        archive.writestr(entry, "SKILL.md")
    with pytest.raises(ValueError, match="不安全"):
        inspect_package(path, installed_versions={})


def test_expansion_limit_rejected(tmp_path):
    path = package(tmp_path)
    with zipfile.ZipFile(path, "a", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("large.txt", b"a" * (4 * 1024 * 1024 + 1))
    with pytest.raises(ValueError, match="超过限制"):
        inspect_package(path, installed_versions={})


def test_case_colliding_files_rejected(tmp_path):
    path = package(tmp_path, entries={"skill.md": "duplicate"})
    with pytest.raises(ValueError, match="重复文件"):
        inspect_package(path, installed_versions={})
