"""Build the project-oriented client without replacing the legacy desktop."""

import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUILTIN_SKILL_RESOURCES = (
    'gongshang-change-history-docx',
    'valuation-detail-workbook-fill',
    'financial-brief-docx',
    'office-workflow-to-skill',
)


def builtin_data_arguments(build):
    """Stage only reviewed skill sources and curated templates, never user runs."""
    arguments = []
    for skill in BUILTIN_SKILL_RESOURCES:
        source = ROOT / '.codex/skills' / skill
        target = build / 'release_resources' / 'builtin_skills' / skill
        for path in source.rglob('*'):
            if (path.is_file() and '__pycache__' not in path.parts
                    and path.suffix in {'.py', '.md', '.json', '.yaml', '.docx', '.vbs'}):
                dest = target / path.relative_to(source)
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(path, dest)
        template_source = ROOT / 'assets/builtin_templates' / skill
        if template_source.is_dir():
            for path in template_source.iterdir():
                if path.is_file() and path.suffix in {'.xlsx', '.docx', '.json'}:
                    dest = target / 'assets' / path.name
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(path, dest)
        arguments += ['--add-data', f'{target}{os.pathsep}builtin_skills/{skill}']
    return arguments


def main():
    build = ROOT / "build" / "technical_platform"
    build.mkdir(parents=True, exist_ok=True)
    environment = os.environ.copy()
    # Do not resolve Qt's Windows ICU imports against unrelated tool runtimes.
    environment["PATH"] = os.pathsep.join(
        [
            str(Path(sys.executable).parent),
            str(Path(os.environ["WINDIR"]) / "System32"),
            os.environ["WINDIR"],
        ]
    )
    client = subprocess.run(
        [
            sys.executable,
            "-m",
            "PyInstaller",
            "--noconfirm",
            "--clean",
            "--windowed",
            "--name",
            "ZQ技术平台",
            "--icon",
            str(ROOT / "assets/report_review/zq_app_icon.ico"),
            "--add-data",
            f"{ROOT / 'src/asset_based_agent/technical_platform/review_rules.txt'}{os.pathsep}asset_based_agent/technical_platform",
            "--add-data",
            f"{ROOT / 'src/asset_based_agent/technical_platform/builtin_contracts'}{os.pathsep}asset_based_agent/technical_platform/builtin_contracts",
            "--hidden-import",
            "win32cred",
            "--hidden-import",
            "pywintypes",
            "--hidden-import",
            "win32com.client",
            "--hidden-import",
            "pythoncom",
            "--hidden-import",
            "asset_based_agent.technical_platform.feedback_service",
            "--hidden-import",
            "asset_based_agent.technical_platform.memory_contracts",
            "--hidden-import",
            "asset_based_agent.technical_platform.memory_retrieval",
            "--hidden-import",
            "asset_based_agent.technical_platform.memory_service",
            "--hidden-import",
            "asset_based_agent.technical_platform.review_issues",
            "--hidden-import",
            "asset_based_agent.technical_platform.skill_improvement",
            "--hidden-import",
            "asset_based_agent.technical_platform.ui.memory_panel",
            "--copy-metadata",
            "python-docx",
            "--copy-metadata",
            "openpyxl",
            "--copy-metadata",
            "pdfplumber",
            "--copy-metadata",
            "httpx",
            "--copy-metadata",
            "pydantic",
            "--copy-metadata",
            "packaging",
            "--distpath",
            str(ROOT / "dist/technical_platform"),
            "--workpath",
            str(build),
            "--specpath",
            str(build),
            "--paths",
            str(ROOT / "src"),
            *builtin_data_arguments(build),
            str(ROOT / "scripts/run_technical_platform.py"),
        ],
        cwd=ROOT,
        env=environment,
        check=False,
    ).returncode
    if client:
        return client
    bootstrap = ROOT / "dist/technical_platform/bootstrap"
    bootstrap.mkdir(parents=True, exist_ok=True)
    for name, script in (
        ("ZQ技术平台更新器", "run_client_updater.py"),
        ("ZQ技术平台启动器", "run_client_launcher.py"),
    ):
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "PyInstaller",
                "--noconfirm",
                "--clean",
                "--onefile",
                "--windowed",
                "--name",
                name,
                "--icon",
                str(ROOT / "assets/report_review/zq_app_icon.ico"),
                "--distpath",
                str(bootstrap),
                "--workpath",
                str(build / name),
                "--specpath",
                str(build / name),
                "--paths",
                str(ROOT / "src"),
                str(ROOT / "scripts" / script),
            ],
            cwd=ROOT,
            env=environment,
            check=False,
        ).returncode
        if result:
            return result
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
