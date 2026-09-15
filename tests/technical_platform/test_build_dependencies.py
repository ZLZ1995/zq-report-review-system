import importlib.util
from pathlib import Path
from types import SimpleNamespace


def test_build_includes_office_modules_used_by_bundled_scripts(monkeypatch):
    script = Path(__file__).resolve().parents[2] / 'scripts/build_technical_platform.py'
    spec = importlib.util.spec_from_file_location('build_platform_test', script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    calls = []
    monkeypatch.setattr(module, 'builtin_data_arguments', lambda _: [])
    monkeypatch.setattr(module.subprocess, 'run', lambda args, **kw: calls.append(args) or SimpleNamespace(returncode=0))
    assert module.main() == 0
    args = calls[0]
    imports = [args[i + 1] for i, arg in enumerate(args[:-1]) if arg == '--hidden-import']
    assert 'win32com.client' in imports
    assert 'pythoncom' in imports
