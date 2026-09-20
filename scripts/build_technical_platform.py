"""Build the project-oriented client without replacing the legacy desktop."""

import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# G11：允许用环境变量把构建产物放到新的 D 盘时间戳目录，不覆盖旧验收包。
DIST_ROOT = Path(os.environ.get("TP_DIST_ROOT", ROOT / "dist/technical_platform"))
BUILD_WORK = Path(os.environ.get("TP_BUILD_WORK", ROOT / "build/technical_platform"))
# G02-G10 新增 Agent/Harness 模块必须随冻结包分发；多期间资料消歧/恢复模块同样
# 仅在运行路径中按需导入，静态分析不可见，必须显式列入。
NEW_HARNESS_MODULES = (
    "agent_profiles", "context_budget", "context_manifest",
    "material_analysis", "material_resume",
    "conversation_compactor", "conversation_stream", "diagnostic_bundle",
    "evidence_retriever", "failure_drills", "input_gateway", "intent_policy",
    "intent_schema", "memory_candidates", "memory_consolidation",
    "memory_selector", "platform_queries", "skill_contract_v2", "task_panel",
    "turn_context", "turn_router",
    "turn_normalizer", "turn_scope_policy", "workflow_compiler",
    "workflow_events", "workflow_journal", "workflow_plan",
    "workflow_reconciliation", "workflow_runtime", "workflow_scheduler",
)


def hidden_import_arguments():
    arguments = []
    for module in NEW_HARNESS_MODULES:
        arguments += ["--hidden-import",
                      f"asset_based_agent.technical_platform.{module}"]
    return arguments
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
    build = BUILD_WORK
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
            *hidden_import_arguments(),
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
            str(DIST_ROOT),
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
    bootstrap = DIST_ROOT / "bootstrap"
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
