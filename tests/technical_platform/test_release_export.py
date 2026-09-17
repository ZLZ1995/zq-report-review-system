"""Release inventory must not traverse runtime data or redirected files."""

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest


def exporter():
    script = Path(__file__).resolve().parents[2] / "scripts/export_client_release.py"
    spec = importlib.util.spec_from_file_location("release_export", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_runtime_directories_are_not_release_sources(tmp_path):
    module = exporter()
    package = tmp_path / "src/asset_based_agent/technical_platform"
    package.mkdir(parents=True)
    safe = package / "storage_migration.py"
    safe.write_text("# source", encoding="utf-8")
    for folder in ("runs", "outputs", "__pycache__", "credentials", "downloads"):
        target = package / folder / "customer.py"
        target.parent.mkdir()
        target.write_text("private", encoding="utf-8")
    assert module.collect_paths(tmp_path, require_explicit=False) == {safe}


def test_release_rejects_redirected_source(tmp_path, monkeypatch):
    module = exporter()
    package = tmp_path / "src/asset_based_agent/technical_platform"
    package.mkdir(parents=True)
    secret = tmp_path / "private.txt"
    secret.write_text("private", encoding="utf-8")
    redirected = package / "redirect.py"
    redirected.write_text("# redirected source", encoding="utf-8")
    original_resolve = Path.resolve

    def resolve(path, *args, **kwargs):
        if path == redirected:
            return secret
        return original_resolve(path, *args, **kwargs)

    monkeypatch.setattr(Path, "resolve", resolve)
    with pytest.raises(ValueError, match="redirect"):
        module.collect_paths(tmp_path, require_explicit=False)


def test_actual_release_contains_new_acceptance_tools():
    module = exporter()
    names = {p.relative_to(module.ROOT).as_posix() for p in module.collect_paths(module.ROOT)}
    for name in (
        "scripts/check_agent_release_baseline.py",
        "scripts/check_technical_platform.py",
        "scripts/probe_platform_webengine.py",
        "scripts/build_platform_webengine_probe.py",
        "docs/technical_platform/delivery/PROTOCOL_COMPATIBILITY.md",
        "src/asset_based_agent/technical_platform/storage_migration.py",
        "src/asset_based_agent/agent_contracts.py",
        "src/asset_based_agent/browser_contracts.py",
        "src/asset_based_agent/technical_platform/builtin_contracts/detail_workbook.json",
        "src/asset_based_agent/report_review_server/prompts/task_understanding.txt",
        "tests/report_review_server/test_admin_billing_ui.cjs",
        "tests/report_review_server/test_admin_discovery_ui.cjs",
        "tests/agent_acceptance/corpus.py",
        "tests/agent_acceptance/scoring.py",
        "tests/agent_acceptance/cases/intent.jsonl",
        "tests/agent_acceptance/cases/dialogue.jsonl",
        "tests/agent_acceptance/cases/scope.jsonl",
        "tests/agent_acceptance/cases/permissions.jsonl",
        "tests/agent_acceptance/cases/recovery.jsonl",
        "tests/agent_acceptance/cases/holdout.jsonl",
        "tests/agent_acceptance/cases/manifest.json",
        "scripts/evaluate_agent_semantics.py",
        "scripts/run_agent_e2e.py",
        "tests/technical_platform/test_agent_e2e_runner.py",
        "scripts/probe_admin_billing_browser.cjs",
        "docs/report_review_productization/openapi-v1.yaml",
    ):
        assert name in names


def test_browser_and_semantic_inventory_does_not_collect_runtime_evidence(tmp_path):
    module = exporter()
    files = ['tests/report_review_server/test_admin_billing_ui.cjs',
             'tests/report_review_server/arbitrary.cjs',
             'tests/agent_acceptance/observations.json',
             'tests/agent_acceptance/cases/private.jsonl']
    for name in files:
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text('synthetic', encoding='utf-8')
    names = {p.relative_to(tmp_path).as_posix() for p in module.collect_paths(tmp_path, require_explicit=False)}
    assert names == {files[0]}


def test_manifest_records_exact_bytes_without_source_content(tmp_path, monkeypatch):
    module = exporter()
    source = tmp_path / 'module.py'
    raw = b'# synthetic private content, not emitted\n'
    source.write_bytes(raw)
    monkeypatch.setattr(module, 'collect_paths', lambda root: {source})
    target = tmp_path / 'outputs/nl_acceptance/candidate.json'
    module.write_manifest(tmp_path, target)
    data = json.loads(target.read_text(encoding='utf-8'))
    assert data['status'] == 'candidate_not_release_approved'
    assert data['files'] == [{'path': 'module.py', 'size': len(raw),
                              'sha256': hashlib.sha256(raw).hexdigest(),
                              'git_sha': hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()}]
    assert 'synthetic private content' not in target.read_text(encoding='utf-8')
    with pytest.raises(FileExistsError):
        module.write_manifest(tmp_path, target)


def test_manifest_cannot_write_outside_acceptance_directory(tmp_path):
    module = exporter()
    with pytest.raises(ValueError, match='acceptance'):
        module.write_manifest(tmp_path, tmp_path / 'wrong.json')
    assert not (tmp_path / 'wrong.json').exists()
