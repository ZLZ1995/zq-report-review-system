"""Determine source scope before any template structure scan or write."""
import argparse
import json
from pathlib import Path

import run_detail_workbook_pipeline as pipeline


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--trial-balance', required=True)
    parser.add_argument('--balance-sheet', required=True)
    parser.add_argument('--project-mapping', required=True)
    parser.add_argument('--journal')
    parser.add_argument('--bank-statement', action='append', default=[])
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    selected = pipeline.select_latest_statement([args.balance_sheet])
    bs = pipeline.parse_balance_sheet(Path(args.balance_sheet), cover_source=selected)
    values = bs['values']
    total = next((values[key] for key in ('负债和所有者权益合计', '负债及所有者权益总计',
                 '负债和所有者权益总计', '负债和所有者权益（或股东权益）合计') if key in values), None)
    if total is None or '资产总计' not in values or abs(values['资产总计'] - total) >= 0.005:
        raise ValueError('原始资产负债表不平衡或缺少合计行；尚未扫描或修改模板')
    mapping = json.loads(Path(args.project_mapping).read_text('utf-8'))
    tb = pipeline.load_trial_balance_rows(Path(args.trial_balance))
    journal = pipeline.load_journal_rows(Path(args.journal) if args.journal else None)
    banks, _ = pipeline.load_bank_statement_evidence(args.bank_statement, values)
    plan = pipeline.group_rows_for_y71(mapping, tb, values,
        pipeline.build_journal_entity_index(journal), pipeline.build_journal_fallback_index(journal))
    scope = pipeline.select_execution_scope(values, plan, bank_evidence_available=bool(banks))
    # Preserve source-level scope for the pipeline; no extra file discovery.
    Path(args.output).write_text(json.dumps(scope, ensure_ascii=False, indent=2), 'utf-8')


if __name__ == '__main__':
    main()
