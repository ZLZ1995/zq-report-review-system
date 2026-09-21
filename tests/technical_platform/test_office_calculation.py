import importlib.util
from pathlib import Path

import pytest


def module():
    path = Path('.codex/skills/valuation-detail-workbook-fill/scripts/recalculate_readonly.py')
    spec = importlib.util.spec_from_file_location('office_calculation_test', path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def test_excel_unavailable_falls_back_to_wps():
    calls = []
    app = object()
    def dispatch(name):
        calls.append(name)
        if name == 'Excel.Application':
            raise OSError('not installed')
        return app
    actual, engine = module().create_calculation_application(dispatch)
    assert actual is app
    assert engine == 'WPS'
    assert calls == ['Excel.Application', 'ket.Application']


def test_no_office_reports_actionable_failure():
    def dispatch(name):
        raise OSError('not installed')
    with pytest.raises(RuntimeError, match='Excel.*WPS'):
        module().create_calculation_application(dispatch)


def test_wps_uses_full_calculation():
    class Wps:
        called = False
        def CalculateFull(self):
            self.called = True
    app = Wps()
    module().calculate_all(app, 'WPS')
    assert app.called


def test_formula_values_are_read_in_bounded_batches():
    from types import SimpleNamespace
    calls = []
    class Sheet:
        def Range(self, address):
            calls.append(address)
            assert address == 'A1:A100'
            return SimpleNamespace(Value2=tuple((i,) for i in range(1, 101)))
    result = module().read_formula_values(Sheet(), [f'A{i}' for i in range(1, 101)])
    assert result['A100'] == 100
    assert calls == ['A1:A100']


def test_standard_formula_errors_do_not_require_per_cell_com_calls():
    from types import SimpleNamespace
    class Sheet:
        def Range(self, address):
            assert address == 'A1:A2'
            return SimpleNamespace(Value2=((-2146826281,), (-2146826265,)))
    assert module().read_formula_values(Sheet(), ['A1', 'A2']) == {'A1': '#DIV/0!', 'A2': '#REF!'}


def test_close_failure_still_quits_owned_instance(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from openpyxl import Workbook
    path = tmp_path / 'source.xlsx'
    Workbook().save(path)
    original = path.read_bytes()
    class Book:
        def Close(self, **kwargs):
            raise RuntimeError('close failed')
    class App:
        quit_called = False
        Workbooks = SimpleNamespace(Count=0, Open=lambda *a, **kw: Book())
        def CalculateFull(self):
            raise RuntimeError('calculation failed')
        def Quit(self):
            self.quit_called = True
    app, m = App(), module()
    monkeypatch.setattr(m, 'create_calculation_application', lambda: (app, 'WPS'))
    with pytest.raises(RuntimeError):
        m.recalculate_formula_caches(path)
    assert app.quit_called
    assert path.read_bytes() == original


def test_user_workbook_instance_is_not_modified_or_closed(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from openpyxl import Workbook
    path = tmp_path / 'source.xlsx'
    Workbook().save(path)
    class App:
        Workbooks = SimpleNamespace(Count=1)
        def __setattr__(self, name, value):
            raise AssertionError('user instance modified')
        def Quit(self):
            raise AssertionError('user instance closed')
    m = module()
    monkeypatch.setattr(m, 'create_calculation_application', lambda: (App(), 'WPS'))
    with pytest.raises(RuntimeError, match='现有工作簿未关闭'):
        m.recalculate_formula_caches(path)
