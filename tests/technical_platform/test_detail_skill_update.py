import json
from pathlib import Path

from asset_based_agent.technical_platform import generation, generation_worker
from asset_based_agent.technical_platform.skills import DETAIL


def test_bank_statement_can_be_assigned_by_client():
    files = [{'id': 'tb', 'name': 'tb.xlsx'}, {'id': 'bs', 'name': 'bs.xlsx'},
             {'id': 'bank', 'name': 'bank.xlsx'}]
    generation.validate_roles(DETAIL.id, files,
        {'trial_balance': 'tb', 'balance_sheet': 'bs', 'bank_statement': 'bank'})


def test_detail_skill_is_bound_to_approved_template():
    approved = Path(__file__).resolve().parents[2] / 'assets/builtin_templates' / DETAIL.id / 'template.xlsx'
    assert generation.locked_template(DETAIL.id).read_bytes() == approved.read_bytes()


def test_worker_forwards_bank_and_scope_mode(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(generation_worker, 'call', lambda script, args: calls.append((script.name, args)))
    (tmp_path / 'completion_status.json').write_text(json.dumps({'status': 'complete'}))
    (tmp_path / 'detail_workbook.xlsx').touch()
    generation_worker.detail(tmp_path, {'trial_balance': 'tb.xlsx', 'balance_sheet': 'bs.xlsx',
        'template': 'template.xlsx', 'bank_statement': 'bank.xlsx'}, tmp_path)
    args = next(args for name, args in calls if name == 'run_detail_workbook_pipeline.py')
    assert args[args.index('--bank-statement') + 1] == 'bank.xlsx'
    assert args[args.index('--execution-mode') + 1] == 'auto'


def test_scope_is_prepared_before_template_scan(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(generation_worker, 'call', lambda script, args: calls.append((script.name, args)))
    (tmp_path / 'completion_status.json').write_text(json.dumps({'status': 'blocked'}))
    generation_worker.detail(tmp_path, {'trial_balance': 'tb.xlsx', 'balance_sheet': 'bs.xlsx',
        'template': 'template.xlsx'}, tmp_path)
    names = [name for name, _ in calls]
    assert names.index('prepare_execution_scope.py') < names.index('scan_template_structure.py')
    scan_args = next(args for name, args in calls if name == 'scan_template_structure.py')
    assert '--execution-scope' in scan_args


def test_worker_forwards_all_financial_statements_latest_first(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(generation_worker, 'call', lambda script, args: calls.append((script.name, args)))
    (tmp_path / 'completion_status.json').write_text(json.dumps({'status': 'complete'}))
    (tmp_path / 'detail_workbook.xlsx').touch()
    generation_worker.detail(tmp_path, {'balance_sheet': 'bs2026.xlsx', 'template': 'template.xlsx',
        'financial_statements': ['bs2026.xlsx', 'bs2025.xlsx', 'bs2024.xlsx']}, tmp_path)
    args = next(args for name, args in calls if name == 'run_detail_workbook_pipeline.py')
    picked = [args[i + 1] for i, a in enumerate(args) if a == '--financial-statement']
    assert picked == ['bs2026.xlsx', 'bs2025.xlsx', 'bs2024.xlsx']
    assert args[args.index('--balance-sheet') + 1] == 'bs2026.xlsx'


def test_worker_without_statement_list_keeps_legacy_single_flag(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(generation_worker, 'call', lambda script, args: calls.append((script.name, args)))
    (tmp_path / 'completion_status.json').write_text(json.dumps({'status': 'complete'}))
    (tmp_path / 'detail_workbook.xlsx').touch()
    generation_worker.detail(tmp_path, {'balance_sheet': 'bs.xlsx', 'template': 'template.xlsx'}, tmp_path)
    args = next(args for name, args in calls if name == 'run_detail_workbook_pipeline.py')
    picked = [args[i + 1] for i, a in enumerate(args) if a == '--financial-statement']
    assert picked == ['bs.xlsx']
