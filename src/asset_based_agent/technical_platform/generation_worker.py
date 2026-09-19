"""Private subprocess entry for the two trusted built-in generators."""

import json
import re
import runpy
import shutil
import sys
from datetime import date
from pathlib import Path

from .generation import bundle_directory
from .skills import DETAIL, FINANCIAL_BRIEF, HISTORY, WORKFLOW_TO_SKILL


def call(script, args):
    sys.argv = [str(script), *map(str, args)]
    try:
        runpy.run_path(str(script), run_name='__main__')
    except SystemExit as exc:
        if exc.code not in (None, 0):
            raise RuntimeError(f'{script.name} 验收未通过（退出码 {exc.code}）') from exc


def detail(scripts, inputs, output):
    bs, template = inputs['balance_sheet'], inputs['template']
    tb = ['--trial-balance', inputs['trial_balance']] if inputs.get('trial_balance') else []
    mapping, chain = output / 'project_mapping.json', output / 'formula_chain_map.json'
    layout, protection = output / 'sheet_structure_map.json', output / 'formula_protection_report.json'
    registry, summary = output / 'input_cell_registry.json', output / 'summary_chain_input_registry.json'
    journal = ['--journal', inputs['journal']] if inputs.get('journal') else []
    bank = ['--bank-statement', inputs['bank_statement']] if inputs.get('bank_statement') else []
    stages = [
        ('build_project_mapping.py', [*tb, '--balance-sheet', bs, *journal, '--output', mapping]),
        ('prepare_execution_scope.py', [*tb, '--balance-sheet', bs,
            '--project-mapping', mapping, *journal, *bank, '--output', output / 'execution_scope.json']),
        ('build_formula_chain_map.py', ['--template', template, '--output', chain]),
        ('scan_template_structure.py', ['--template', template, '--layout-output', layout, '--protection-output', protection,
            '--execution-scope', output / 'execution_scope.json']),
        ('build_input_cell_registry.py', ['--layout-map', layout, '--output', registry]),
        ('build_summary_chain_input_registry.py', ['--layout-map', layout, '--input-cell-registry', registry, '--output', summary]),
        ('run_detail_workbook_pipeline.py', [*tb, '--balance-sheet', bs,
            '--financial-statement', bs, *journal, *bank, '--execution-mode', 'auto',
            '--template', template, '--output-dir', output,
            '--published-workbook', output / 'detail_workbook.xlsx', '--project-mapping', mapping,
            '--formula-chain', chain, '--sheet-layout', layout, '--formula-protection', protection,
            '--input-cell-registry', registry, '--summary-chain-input-registry', summary,
            '--allow-excel-recalc']),
    ]
    for name, args in stages:
        call(scripts / name, args)
    status = json.loads((output / 'completion_status.json').read_text(encoding='utf-8'))
    return status.get('status') == 'complete' and (output / 'detail_workbook.xlsx').is_file()


def _financial_metadata(path):
    from openpyxl import load_workbook  # type: ignore[import-untyped]

    book = load_workbook(path, read_only=True, data_only=True)
    try:
        sheet = book['资产负债表']
        values = [str(cell.value).strip() for row in sheet.iter_rows(max_row=4)
                  for cell in row if cell.value not in (None, '')]
    finally:
        book.close()
    text = ' '.join(values)
    match = re.search(r'(\d{4})年(\d{1,2})月(\d{1,2})日', text)
    if match is None:
        raise ValueError('资产负债表表头缺少完整报表日期')
    unit = next((item for item in values if '编制单位' in item or '单位名称' in item), '')
    company = re.sub(r'.*(?:编制单位|单位名称)[:：]?\s*', '', unit).strip() if unit else ''
    if company and not re.search(r'\d{4}年\d{1,2}月', company) and company != '元':
        return company, date(*map(int, match.groups()))
    excluded = ('资产负债表', '编制单位', '单位', '日期')
    candidates = [re.sub(r'^编制单位[:：]?\s*', '', item).strip()
                  for item in values if not any(token in item for token in excluded)
                  and not re.search(r'\d{4}年\d{1,2}月', item)]
    company = max(candidates, key=len, default='')
    if not company:
        raise ValueError('资产负债表表头缺少企业名称')
    return company, date(*map(int, match.groups()))


def financial_brief(scripts, inputs, output):
    records = []
    for role in ('period_one', 'period_two', 'basis_date'):
        path = Path(inputs[role])
        company, report_date = _financial_metadata(path)
        records.append((role, path, company, report_date))
    companies = {item[2] for item in records}
    if len(companies) != 1:
        raise ValueError('三份财务报表的企业名称不一致')
    ordered = sorted(records, key=lambda item: item[3])
    sources = []
    for index, (_role, path, _company, report_date) in enumerate(ordered):
        full_year = report_date.month == 12 and report_date.day == 31 and index < 2
        sources.append({
            'path': str(path), 'date': report_date.isoformat(),
            'balance_label': f'{report_date.year}年{report_date.month}月{report_date.day}日',
            'income_label': (f'{report_date.year}年度' if full_year else
                             f'{report_date.year}年1—{report_date.month}月'),
        })
    poppler = shutil.which('pdftoppm') or shutil.which('pdftoppm.exe')
    generated = output / 'generated'
    config = output.parent / 'financial_brief_job.json'
    config.write_text(json.dumps({
        'output_dir': str(generated), 'sources': sources, 'company': next(iter(companies)),
        'template': inputs['template'], 'poppler': poppler,
    }, ensure_ascii=False), encoding='utf-8')
    call(scripts / 'run_brief.py', [config])
    for path in generated.iterdir():
        if path.is_file():
            shutil.copyfile(path, output / path.name)
    pages = list(generated.glob('page-*.png'))
    if len(pages) == 1:
        shutil.copyfile(pages[0], output / 'financial_brief.png')
    return all((output / name).is_file() for name in
               ('financial_brief.docx', 'financial_brief.pdf', 'financial_brief.png',
                'extraction.json', 'timing.json'))


def workflow_contract(scripts, inputs, output):
    report = output / 'office_workflow_contract_validation.json'
    call(scripts / 'validate_workflow_contract.py',
         ['--contract', inputs['workflow_contract'], '--output', report])
    return report.is_file() and json.loads(report.read_text(encoding='utf-8')).get('ok') is True


def main(job_path):
    job_path = Path(job_path).resolve()
    job = json.loads(job_path.read_text(encoding='utf-8'))
    output = job_path.parent / 'output'
    output.mkdir(exist_ok=False)
    ok = False
    try:
        scripts = bundle_directory(job['skill_id']) / 'scripts'
        sys.path.insert(0, str(scripts))
        if job['skill_id'] == HISTORY.id:
            from .history_generation import generate
            ok = generate(scripts, job['inputs'], output)
        elif job['skill_id'] == DETAIL.id:
            ok = detail(scripts, job['inputs'], output)
        elif job['skill_id'] == FINANCIAL_BRIEF.id:
            ok = financial_brief(scripts, job['inputs'], output)
        elif job['skill_id'] == WORKFLOW_TO_SKILL.id:
            ok = workflow_contract(scripts, job['inputs'], output)
        else:
            raise PermissionError('未注册的生成器')
    except Exception as exc:  # noqa: BLE001 - subprocess boundary must emit failure feedback
        import traceback
        traceback.print_exc()
        feedback = output / 'user_feedback.md'
        if not feedback.exists():
            feedback.write_text(f'未通过生成验收，没有发布正式成果。\n{type(exc).__name__}: {exc}\n'
                                '请检查所选模板、来源布局与必要资料；不支持的布局不会强行填写。', encoding='utf-8')
    (job_path.parent / 'status.json').write_text(json.dumps({'ok': ok}), encoding='utf-8')
    return 0 if ok else 2


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1]))
