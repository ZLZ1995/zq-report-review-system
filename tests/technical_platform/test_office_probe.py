import importlib.util
import os
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.mark.skipif(os.name != 'nt', reason='Windows COM probe safety')
@pytest.mark.parametrize('existing,books,may_quit', [(True, 0, False), (False, 2, False), (False, 0, True)])
def test_probe_never_quits_existing_or_nonempty_instance(monkeypatch, existing, books, may_quit):
    import win32com.client
    import win32process
    root = Path(__file__).resolve().parents[2]
    spec = importlib.util.spec_from_file_location('office_probe', root / 'scripts/probe_office_startup.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    closed = []
    app = SimpleNamespace(Hwnd=123, Workbooks=SimpleNamespace(Count=books), Quit=lambda: closed.append(True))
    monkeypatch.setattr(win32process, 'EnumProcesses', lambda: [42] if existing else [])
    monkeypatch.setattr(win32process, 'GetWindowThreadProcessId', lambda _: (1, 42))
    monkeypatch.setattr(win32com.client, 'DispatchEx', lambda _: app)
    result = module.probe('Excel.Application')
    assert bool(closed) is may_quit
    assert result['opened_documents'] is False
    assert result['status'] == ('startup_verified' if may_quit else 'existing_instance_not_modified')
