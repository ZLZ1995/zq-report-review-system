"""Emit an explicit client-source release allowlist as JSON (no user data)."""

import base64
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    paths = set()
    for folder in ("src/asset_based_agent/technical_platform", "src/asset_based_agent/report_review_app",
                   "tests/technical_platform", "tests/report_review_app"):
        paths.update(p for p in (ROOT / folder).rglob("*.py") if "__pycache__" not in p.parts)
    for folder in ("docs/technical_platform",):
        paths.update((ROOT / folder).glob("*.md"))
        paths.update((ROOT / folder).glob("*.txt"))
    for name in (
        "src/asset_based_agent/technical_platform/review_rules.txt",
        "src/asset_based_agent/llm/__init__.py", "src/asset_based_agent/llm/config.py",
        "src/asset_based_agent/reporting/__init__.py",
        "src/asset_based_agent/reporting/valuation_report_structure.py",
        "scripts/run_technical_platform.py", "scripts/build_technical_platform.py",
        "scripts/smoke_technical_platform_exe.py", "scripts/test_report_review_productization.py",
        "scripts/export_client_release.py", "assets/report_review/zq_app_icon.ico",
    ):
        paths.add(ROOT / name)
    output = []
    for path in sorted(paths):
        raw = path.read_bytes()
        binary = path.suffix == ".ico"
        output.append({"path": path.relative_to(ROOT).as_posix(),
                       "content": base64.b64encode(raw).decode() if binary else raw.decode("utf-8-sig"),
                       "encoding": "base64" if binary else "utf-8",
                       "git_sha": hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()})
    serialized = json.dumps(output, ensure_ascii=False)
    start = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    count = int(sys.argv[2]) if len(sys.argv) > 2 else 20000
    print(json.dumps({"total": len(serialized), "chunk": serialized[start:start + count]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
