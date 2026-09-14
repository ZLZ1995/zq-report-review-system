"""Private subprocess entry for the two trusted built-in generators."""

import json
import runpy
import sys
from pathlib import Path

from .generation import bundle_directory
from .skills import DETAIL, HISTORY


def call(script, args):
    sys.argv = [str(script), *map(str, args)]
    try:
        runpy.run_path(str(script), run_name='__main__')
    except SystemExit as exc:
        if exc.code not in (None, 0):
            raise RuntimeError(f'{script.name} 验收未通过（退出码 {exc.code}）') from exc


def detail(scripts, inputs, output):
    tb, bs, template = inputs['trial_balance'], inputs['balance_sheet'], inputs['template']
    mapping, chain = output / 'project_mapping.json', output / 'formula_chain_map.json'
    layout, protection = output / 'sheet_structure_map.json', output / 'formula_protection_report.json'
    registry, summary = output / 'input_cell_registry.json', output / 'summary_chain_input_registry.json'
    journal = ['--journal', inputs['journal']] if inputs.get('journal') else []
    stages = [
        ('build_project_mapping.py', ['--trial-balance', tb, '--balance-sheet', bs, *journal, '--output', mapping]),
        ('build_formula_chain_map.py', ['--template', template, '--output', chain]),
        ('scan_template_structure.py', ['--template', template, '--layout-output', layout, '--protection-output', protection]),
        ('build_input_cell_registry.py', ['--layout-map', layout, '--output', registry]),
        ('build_summary_chain_input_registry.py', ['--layout-map', layout, '--input-cell-registry', registry, '--output', summary]),
        ('run_detail_workbook_pipeline.py', ['--trial-balance', tb, '--balance-sheet', bs,
            '--financial-statement', bs, *journal, '--template', template, '--output-dir', output,
            '--published-workbook', output / 'detail_workbook.xlsx', '--project-mapping', mapping,
            '--formula-chain', chain, '--sheet-layout', layout, '--formula-protection', protection,
            '--input-cell-registry', registry, '--summary-chain-input-registry', summary,
            '--skip-excel-recalc']),
    ]
    for name, args in stages:
        call(scripts / name, args)
    status = json.loads((output / 'completion_status.json').read_text(encoding='utf-8'))
    return status.get('status') == 'complete' and (output / 'detail_workbook.xlsx').is_file()


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
            raise ValueError('工商锁定模板的填充区域尚未确认，禁止使用通用重建版式代替')
        elif job['skill_id'] == DETAIL.id:
            ok = detail(scripts, job['inputs'], output)
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
