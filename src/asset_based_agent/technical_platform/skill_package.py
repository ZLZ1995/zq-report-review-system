"""Inspect data-only Skill archives without extraction, imports or dependency installs."""

import hashlib
import io
import json
import re
import stat
import zipfile
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path, PurePosixPath

from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.version import InvalidVersion, Version

MAX_PACKAGE_BYTES = 2 * 1024 * 1024
MAX_EXPANDED_BYTES = 4 * 1024 * 1024
CAPABILITIES = {
    "report.review": {"read_selected_files", "generate_artifacts"},
    "review.preflight": {"read_selected_files"},
}


@dataclass(frozen=True)
class InspectedPackage:
    manifest: dict
    instructions: str
    sha256: str
    missing_dependencies: tuple[str, ...]

    @property
    def ready(self) -> bool:
        return not self.missing_dependencies


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Skill JSON 存在重复字段")
        result[key] = value
    return result


def _safe_name(name: str) -> bool:
    path = PurePosixPath(name)
    return (bool(name) and not path.is_absolute() and "\\" not in name
            and ":" not in name and "\x00" not in name
            and all(part not in {"", ".", ".."} for part in name.split("/")))


def inspect_package(path: Path, *, installed_versions: dict[str, str] | None = None) -> InspectedPackage:
    with path.open("rb") as stream:
        raw = stream.read(MAX_PACKAGE_BYTES + 1)
    return inspect_package_bytes(raw, installed_versions=installed_versions)


def inspect_package_bytes(raw: bytes, *, installed_versions: dict[str, str] | None = None) -> InspectedPackage:
    if len(raw) > MAX_PACKAGE_BYTES:
        raise ValueError("Skill 包超过大小限制")
    try:
        return _inspect(raw, installed_versions)
    except (zipfile.BadZipFile, UnicodeError, InvalidSpecifier, InvalidVersion,
            KeyError, TypeError, AttributeError, RuntimeError) as exc:
        raise ValueError("Skill 包格式、依赖或内容无效") from exc


def _inspect(raw: bytes, installed_versions) -> InspectedPackage:
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        entries = archive.infolist()
        if len(entries) > 32 or sum(item.file_size for item in entries) > MAX_EXPANDED_BYTES:
            raise ValueError("Skill 包展开内容超过限制")
        names = [item.filename for item in entries]
        if len({name.casefold() for name in names}) != len(names):
            raise ValueError("Skill 包存在重复文件")
        for item in entries:
            if (not _safe_name(item.filename) or item.is_dir() or item.flag_bits & 1
                    or stat.S_ISLNK(item.external_attr >> 16)):
                raise ValueError("Skill 包路径或文件类型不安全")
        manifest = json.loads(archive.read("manifest.json"), object_pairs_hook=_object)
        required = {"schema_version", "id", "version", "name", "adapter", "capabilities",
                    "dependencies", "files"}
        if not isinstance(manifest, dict) or set(manifest) != required:
            raise ValueError("Skill 清单字段不完整或存在未知字段")
        if type(manifest["schema_version"]) is not int or manifest["schema_version"] != 1:
            raise ValueError("不支持的 Skill 清单版本")
        if not re.fullmatch(r"[a-z][a-z0-9]*(?:[.-][a-z0-9]+)*", manifest["id"]) or len(manifest["id"]) > 80:
            raise ValueError("无效 Skill ID")
        if not re.fullmatch(r"\d+\.\d+\.\d+", manifest["version"]):
            raise ValueError("Skill 版本必须采用数字三段式")
        if not isinstance(manifest["name"], str) or not 1 <= len(manifest["name"].strip()) <= 80:
            raise ValueError("无效 Skill 名称")
        allowed = CAPABILITIES.get(manifest["adapter"])
        caps = manifest["capabilities"]
        if (allowed is None or not isinstance(caps, list) or len(caps) != len(set(caps))
                or not set(caps) <= allowed or "read_selected_files" not in caps):
            raise ValueError("Skill 请求不支持的执行方式或权限")
        files = manifest["files"]
        if not isinstance(files, dict) or "SKILL.md" not in files or set(names) != {"manifest.json", *files}:
            raise ValueError("Skill 包文件与清单不一致")
        for name, expected in files.items():
            if not _safe_name(name) or PurePosixPath(name).suffix.lower() not in {".md", ".txt", ".json"}:
                raise ValueError("Skill 包仅支持说明及数据，不支持脚本")
            if not isinstance(expected, str) or not re.fullmatch(r"[a-f0-9]{64}", expected):
                raise ValueError("无效文件哈希")
            if hashlib.sha256(archive.read(name)).hexdigest() != expected:
                raise ValueError("Skill 文件完整性校验失败")
        instructions = archive.read("SKILL.md").decode("utf-8")
        if not instructions.strip() or len(instructions) > 32000:
            raise ValueError("Skill 说明为空或超过长度限制")
        dependencies = manifest["dependencies"]
        if not isinstance(dependencies, dict) or len(dependencies) > 32:
            raise ValueError("依赖清单无效")
        missing = []
        for name, constraint in sorted(dependencies.items()):
            if not re.fullmatch(r"[A-Za-z0-9]+(?:[._-][A-Za-z0-9]+)*", name):
                raise ValueError("依赖只能声明包名及版本范围")
            if not isinstance(constraint, str) or not constraint or len(constraint) > 120:
                raise ValueError("依赖必须声明版本范围")
            specifier = SpecifierSet(constraint)
            try:
                actual = version(name) if installed_versions is None else installed_versions.get(name)
            except PackageNotFoundError:
                actual = None
            if actual is None or Version(actual) not in specifier:
                missing.append(name + constraint)
        return InspectedPackage(manifest, instructions, hashlib.sha256(raw).hexdigest(), tuple(missing))
