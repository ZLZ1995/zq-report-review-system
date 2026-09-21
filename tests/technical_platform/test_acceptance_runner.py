"""Acceptance entry points must keep synthetic business data off system temp."""

import importlib.util
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]


def load_script(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_platform_runner_uses_explicit_isolated_artifact_directory(monkeypatch):
    import pytest

    module = load_script("check_technical_platform")
    calls = []
    monkeypatch.setattr(pytest, "main", lambda args: calls.append(args) or 0)
    assert module.main() == 0
    assert "--basetemp" in calls[0]
    base = Path(calls[0][calls[0].index("--basetemp") + 1])
    assert base.is_relative_to(ROOT / "outputs" / "nl_acceptance")
    assert base.name == "tmp"
    assert any(arg.startswith("--junitxml=") for arg in calls[0])


def test_productization_runner_includes_platform_with_isolated_processes(monkeypatch):
    module = load_script("test_report_review_productization")
    calls = []

    def run(args, **kwargs):
        calls.append((args, kwargs))
        report = Path(
            next(a.split("=", 1)[1] for a in args if a.startswith("--junitxml="))
        )
        report.write_text(
            '<testsuites><testsuite tests="1" failures="0" errors="0">'
            '<testcase name="synthetic"/></testsuite></testsuites>',
            encoding="utf-8",
        )
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(module.subprocess, "run", run)
    assert module.main() == 0
    assert len(calls) == 4
    bases = []
    for args, kwargs in calls:
        assert args[1:3] == ["-X", "utf8"]
        assert kwargs["timeout"] > 0
        assert kwargs["env"]["QT_QPA_PLATFORM"] == "offscreen"
        base = Path(args[args.index("--basetemp") + 1])
        assert base.is_relative_to(ROOT / "outputs" / "nl_acceptance")
        assert base.parent.is_dir()
        # Leave room for pytest case names and account-scoped browser paths
        # on Windows installations without extended-length path support.
        assert len(str(base.relative_to(ROOT))) <= 65
        bases.append(base)
    assert len(set(bases)) == 4
    assert any("technical_platform" in str(args) for args, _ in calls)


def test_productization_runner_stops_after_failure(monkeypatch):
    module = load_script("test_report_review_productization")
    calls = []
    monkeypatch.setattr(
        module.subprocess,
        "run",
        lambda *args, **kwargs: calls.append(args) or SimpleNamespace(returncode=7),
    )
    assert module.main() == 7
    assert len(calls) == 1


def test_zero_exit_without_report_is_not_a_pass(monkeypatch):
    module = load_script("test_report_review_productization")
    monkeypatch.setattr(
        module.subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=0)
    )
    assert module.main() != 0


def test_explicit_artifact_root_keeps_test_source_and_failure_gate(
    tmp_path, monkeypatch
):
    module = load_script("test_report_review_productization")
    calls = []
    monkeypatch.setattr(
        module.subprocess,
        "run",
        lambda *a, **k: calls.append((a, k)) or SimpleNamespace(returncode=7),
    )
    assert module.main(artifact_root=tmp_path) == 7
    args = calls[0][0][0]
    assert Path(args[args.index("--basetemp") + 1]).is_relative_to(tmp_path)
    assert calls[0][1]["cwd"] == ROOT
    assert str(ROOT / "tests" / "report_review_app") in args


def test_child_output_survives_unavailable_terminal(tmp_path, monkeypatch):
    module = load_script("test_report_review_productization")

    def broken_print(*args, **kwargs):
        raise OSError(22, "synthetic detached terminal")

    monkeypatch.setattr(module, "print", broken_print, raising=False)

    def run(args, **kwargs):
        stream = kwargs["stdout"]
        assert kwargs["stderr"] == module.subprocess.STDOUT
        assert Path(stream.name).is_relative_to(tmp_path)
        stream.write(b"synthetic diagnostic\n")
        return SimpleNamespace(returncode=7)

    monkeypatch.setattr(module.subprocess, "run", run)
    assert module.main(artifact_root=tmp_path) == 7
    assert (
        next(tmp_path.glob("r-*/report_review_app.log")).read_bytes()
        == b"synthetic diagnostic\n"
    )
