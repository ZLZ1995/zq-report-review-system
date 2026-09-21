"""Read-only curated release inventory; never traverse customer input directories."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import platform
import subprocess
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def release_inventory(root: Path) -> list[dict]:
    paths = set((root / 'assets/builtin_templates').rglob('*'))
    for folder in ('technical_platform', 'report_review_app', 'report_review_server'):
        paths.update((root / 'src/asset_based_agent' / folder).rglob('*.py'))
    for skill in ('valuation-detail-workbook-fill', 'gongshang-change-history-docx',
                  'valuation-report-review-edit'):
        folder = root / '.codex/skills' / skill
        paths.update(folder / name for name in ('SKILL.md', 'skill.manifest.yaml', 'template.lock.json'))
    paths.add(root / 'src/asset_based_agent/technical_platform/review_rules.txt')
    return [{'path': path.relative_to(root).as_posix(), 'size': path.stat().st_size,
             'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
            for path in sorted(paths) if path.is_file() and not path.is_symlink()]


def probe() -> dict:
    try:
        head = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT,
                                       timeout=10, text=True).strip()
    except (OSError, subprocess.SubprocessError):
        head = None
    modules = {}
    for name in ('PySide6.QtWebEngineWidgets', 'win32crypt', 'win32com.client'):
        try:
            modules[name] = importlib.util.find_spec(name) is not None
        except (ImportError, ValueError):
            modules[name] = False
    office = {}
    if platform.system() == 'Windows':
        import winreg
        for name in ('Excel.Application', 'Word.Application', 'ket.Application', 'kwps.Application'):
            try:
                with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, name):
                    office[name] = True
            except OSError:
                office[name] = False
    return {'schema_version': 1, 'captured_at': datetime.now(timezone.utc).isoformat(),
            'local_head': head, 'python': platform.python_version(),
            'modules': modules, 'office_registry_only': office,
            'release_inputs': release_inventory(ROOT),
            'online_build': 'not_verified', 'native_office_execution': 'not_verified'}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    text = json.dumps(probe(), ensure_ascii=False, indent=2)
    if args.output:
        target = args.output.resolve()
        if not target.is_relative_to(ROOT / 'outputs/nl_acceptance'):
            parser.error('Report must be under outputs/nl_acceptance')
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            parser.error('Refusing to overwrite baseline evidence')
        target.write_text(text, encoding='utf-8')
        print(target)
    else:
        print(text)


if __name__ == '__main__':
    main()
