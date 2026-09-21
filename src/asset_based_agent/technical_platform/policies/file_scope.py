"""S14 FileScope 接线：为内核运行构造本轮可写根目录集合。

RuleBasedPolicyEngine 已对 local_create/copy_modify/original_modify 的
directory/path/output/destination/target_dir 参数做范围检查；本模块负责
从业务上下文生成 FileScope（项目目录、下载目录、显式附加根）。
"""
from __future__ import annotations

from pathlib import Path

from .contracts import FileScope


def build_file_scope(roots, *, extra_roots=()) -> FileScope:
    """规范化（resolve）并去重；空集合表示不做路径范围检查。"""
    normalized = []
    for root in tuple(roots or ()) + tuple(extra_roots):
        resolved = str(Path(root).resolve())
        if resolved not in normalized:
            normalized.append(resolved)
    return FileScope(roots=tuple(normalized))


def project_file_scope(project_directory, downloads_directory=None, *,
                       extra_roots=()) -> FileScope:
    roots = [project_directory]
    if downloads_directory is not None:
        roots.append(downloads_directory)
    return build_file_scope(roots, extra_roots=extra_roots)
