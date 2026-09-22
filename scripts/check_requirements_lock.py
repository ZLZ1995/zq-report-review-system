"""S8-03 requirements lock 检查：所有依赖必须精确 pin（==版本）。

用法：python scripts/check_requirements_lock.py [requirements.txt ...]
缺省检查 deploy/report_review_server/requirements.txt。
"""
from __future__ import annotations

import sys
from pathlib import Path


def check_file(path: Path) -> list[str]:
    problems: list[str] = []
    for lineno, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith(("#", "-")):
            continue
        requirement = line.split("#", 1)[0].strip()
        if "==" not in requirement:
            problems.append(f"{path}:{lineno}: 未精确 pin: {line}")
        elif any(op in requirement.split("==", 1)[0] for op in (">", "<", "~", "!")):
            problems.append(f"{path}:{lineno}: 混用版本运算符: {line}")
    return problems


def main(argv: list[str]) -> int:
    paths = [Path(a) for a in argv[1:]] or [
        Path("deploy/report_review_server/requirements.txt")]
    problems: list[str] = []
    for path in paths:
        if not path.is_file():
            problems.append(f"{path}: 文件不存在")
            continue
        problems.extend(check_file(path))
    for problem in problems:
        print(problem)
    if problems:
        print(f"requirements lock 检查失败：{len(problems)} 处")
        return 1
    print("requirements lock 检查通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
