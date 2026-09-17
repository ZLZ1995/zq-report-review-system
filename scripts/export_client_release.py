"""Emit an explicit client-source release allowlist as JSON (no user data)."""

import base64
import hashlib
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


EXCLUDED_PARTS = {
    "__pycache__", "runs", "outputs", "credentials", "downloads", "cache",
    "browser_profiles", "update_staging", ".git", ".venv", "node_modules",
}


def collect_paths(root=ROOT, *, require_explicit=True):
    """Collect source candidates only; fail closed on path redirection."""
    paths = set()
    for folder in ("src/asset_based_agent/technical_platform", "src/asset_based_agent/report_review_app",
                   "tests/technical_platform", "tests/report_review_app", "tests/report_review_server"):
        paths.update((root / folder).rglob("*.py"))
    for folder in ("docs/technical_platform",):
        paths.update((root / folder).glob("*.md"))
        paths.update((root / folder).glob("*.txt"))
    paths.update((root / "docs/technical_platform/delivery").glob("*.md"))
    paths.update((root / "src/asset_based_agent/technical_platform/builtin_contracts").glob("*.json"))
    for folder in ('src/asset_based_agent/report_review_server', 'deploy/report_review_server',
                   '.codex/skills/gongshang-change-history-docx',
                   '.codex/skills/valuation-detail-workbook-fill', 'assets/builtin_templates'):
        for path in (root / folder).rglob('*'):
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
        "src/asset_based_agent/agent_contracts.py",
        "src/asset_based_agent/browser_contracts.py",
        "tests/test_gongshang_text_format.py", "tests/test_gongshang_portable_generation.py",
        "tests/test_gongshang_history_fragment_validation.py",
        "tests/test_detail_scope_first.py", "tests/test_detail_locked_writer.py",
        "tests/test_detail_review_release.py", "tests/test_detail_cover_metadata.py",
        "scripts/probe_detail_generation.py", "scripts/verify_detail_template_preservation.py",
        "scripts/package_technical_platform.py",
        "scripts/check_agent_release_baseline.py", "scripts/check_technical_platform.py",
        "scripts/probe_platform_webengine.py", "scripts/build_platform_webengine_probe.py",
        "scripts/probe_office_startup.py",
        "scripts/probe_admin_billing_browser.cjs",
        "tests/report_review_server/test_admin_billing_ui.cjs",
        "tests/report_review_server/test_admin_discovery_ui.cjs",
        "tests/agent_acceptance/README.md",
        "tests/agent_acceptance/corpus.py", "tests/agent_acceptance/scoring.py",
        "tests/agent_acceptance/cases/intent.jsonl",
        "tests/agent_acceptance/cases/dialogue.jsonl",
        "tests/agent_acceptance/cases/scope.jsonl",
        "tests/agent_acceptance/cases/permissions.jsonl",
        "tests/agent_acceptance/cases/recovery.jsonl",
        "tests/agent_acceptance/cases/holdout.jsonl",
        "tests/agent_acceptance/cases/manifest.json",
        "scripts/evaluate_agent_semantics.py",
        "docs/report_review_productization/openapi-v1.yaml",
    ):
        path = root / name
        if require_explicit or path.exists():
            paths.add(path)
    selected = set()
    for path in paths:
        relative = path.relative_to(root)
        if EXCLUDED_PARTS.intersection(relative.parts):
            continue
        if path.resolve() != path.absolute():
            raise ValueError(f"Release source redirect forbidden: {relative}")
        if not path.is_file():
            raise FileNotFoundError(f"Required release source missing: {relative}")
        selected.add(path)
    return selected


def write_manifest(root: Path, target: Path):
    """Freeze candidate hashes without emitting file bodies or authorizing upload."""
    root = root.absolute()
    target = target.absolute()
    allowed = root / 'outputs/nl_acceptance'
    if (root.drive.casefold() == os.environ.get('SystemDrive', 'C:').casefold()
            or not target.is_relative_to(allowed) or target.resolve() != target):
        raise ValueError('Manifest must remain in the non-system acceptance directory')
    if target.exists():
        raise FileExistsError('Refusing to overwrite existing manifest evidence')
    rows = []
    for path in sorted(collect_paths(root)):
        raw = path.read_bytes()
        rows.append({'path': path.relative_to(root).as_posix(), 'size': len(raw),
                     'sha256': hashlib.sha256(raw).hexdigest(),
                     'git_sha': hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()})
    payload = {'schema_version': 1, 'status': 'candidate_not_release_approved', 'files': rows}
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open('x', encoding='utf-8') as stream:
        json.dump(payload, stream, ensure_ascii=False, indent=2)
    return payload


def main():
    if '--manifest-output' in sys.argv:
        target = Path(sys.argv[sys.argv.index('--manifest-output') + 1])
        result = write_manifest(ROOT, target)
        print(json.dumps({'manifest': str(target), 'candidate_files': len(result['files']),
                          'status': result['status']}))
        return
    paths = collect_paths()
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
