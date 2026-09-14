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
                   "tests/technical_platform", "tests/report_review_app", "tests/report_review_server"):
        paths.update(p for p in (ROOT / folder).rglob("*.py") if "__pycache__" not in p.parts)
    for folder in ("docs/technical_platform",):
        paths.update((ROOT / folder).glob("*.md"))
        paths.update((ROOT / folder).glob("*.txt"))
    for folder in ('src/asset_based_agent/report_review_server', 'deploy/report_review_server',
                   '.codex/skills/gongshang-change-history-docx',
                   '.codex/skills/valuation-detail-workbook-fill', 'assets/builtin_templates'):
        for path in (ROOT / folder).rglob('*'):
            if path.is_file() and '__pycache__' not in path.parts and (
                path.suffix in {'.py', '.md', '.txt', '.json', '.yaml', '.ini', '.css', '.js', '.html', '.xlsx', '.docx'}
                or path.name in {'Dockerfile', 'Dockerfile.dockerignore'}
            ):
                paths.add(path)
    for name in (
        "src/asset_based_agent/technical_platform/review_rules.txt",
        "src/asset_based_agent/llm/__init__.py", "src/asset_based_agent/llm/config.py",
        "src/asset_based_agent/reporting/__init__.py",
        "src/asset_based_agent/reporting/valuation_report_structure.py",
        "scripts/run_technical_platform.py", "scripts/build_technical_platform.py",
        "scripts/smoke_technical_platform_exe.py", "scripts/test_report_review_productization.py",
        "scripts/export_client_release.py", "assets/report_review/zq_app_icon.ico",
        "src/asset_based_agent/__init__.py", "scripts/bootstrap_report_review_admin.py",
        "tests/test_gongshang_text_format.py", "tests/test_gongshang_portable_generation.py",
        "tests/test_gongshang_history_fragment_validation.py",
    ):
        paths.add(ROOT / name)
    output = []
    for path in sorted(paths):
        raw = path.read_bytes()
        binary = path.suffix in {'.ico', '.docx', '.xlsx'}
        try:
            decoded = raw.decode('utf-8')
        except UnicodeDecodeError:
            binary = True
            decoded = ''
        output.append({"path": path.relative_to(ROOT).as_posix(),
                       "content": base64.b64encode(raw).decode() if binary else decoded,
                       "encoding": "base64" if binary else "utf-8",
                       "git_sha": hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()})
    serialized = json.dumps(output, ensure_ascii=False)
    if '--index' in sys.argv:
        print(json.dumps([{k: row[k] for k in ('path', 'git_sha', 'encoding')} for row in output]))
        return
    if '--file' in sys.argv:
        wanted = sys.argv[sys.argv.index('--file') + 1]
        record = next(row for row in output if row['path'] == wanted)
        if '--binary' in sys.argv and record['encoding'] != 'base64':
            record['content'] = base64.b64encode(record['content'].encode('utf-8')).decode('ascii')
            record['encoding'] = 'base64'
        if '--part' in sys.argv:
            start = int(sys.argv[sys.argv.index('--part') + 1])
            print(json.dumps({'total': len(record['content']), 'content': record['content'][start:start+24000]}, ensure_ascii=False))
        else:
            print(json.dumps(record, ensure_ascii=False))
        return
    start = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    count = int(sys.argv[2]) if len(sys.argv) > 2 else 20000
    print(json.dumps({"total": len(serialized), "chunk": serialized[start:start + count]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
