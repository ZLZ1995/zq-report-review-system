"""Explicitly authorized built-in generators; no external script execution."""

import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from contextlib import nullcontext
from pathlib import Path

from ..report_review_app.services.resource_locks import CLIENT_RESOURCES
from .generation_paths import generation_work_directory
from .project_catalog import validate_business_directory
from .skills import DETAIL, HISTORY, SourceValidationError, digest

# role, user-facing label, accepted extensions, required
INPUT_ROLES = {
    HISTORY.id: [('source_excel', '工商变更信息', ('.xlsx',), True)],
    DETAIL.id: [('trial_balance', '科目余额表', ('.xlsx', '.xls'), True),
                ('balance_sheet', '原始资产负债表（含单位、期间）', ('.xlsx', '.xls'), True),
                ('journal', '序时账（可选）', ('.xlsx', '.xls'), False),
                ('bank_statement', '银行对账单（可选，标准表头 XLSX）', ('.xlsx',), False)],
}


def bundle_directory(skill_id):
    if skill_id not in INPUT_ROLES:
        raise PermissionError('不支持的本地生成 Skill')
    if getattr(sys, 'frozen', False):
        return Path(sys._MEIPASS) / 'builtin_skills' / skill_id
    return Path(__file__).resolve().parents[3] / '.codex/skills' / skill_id


def bundle_fingerprint(skill_id):
    root = bundle_directory(skill_id)
    locked_template(skill_id)
    if not (root / 'SKILL.md').is_file():
        raise ValueError('内置 Skill 文件缺失，请修复安装')
    result = hashlib.sha256()
    for path in sorted(root.rglob('*')):
        if path.is_file() and path.suffix in {'.py', '.md', '.json', '.yaml'}:
            result.update(path.relative_to(root).as_posix().encode('utf-8'))
            result.update(path.read_bytes())
    return result.hexdigest()


def locked_template(skill_id):
    """Only a release-bound, hash-pinned template can authorize generation."""
    root = bundle_directory(skill_id).resolve()
    lock = root / 'template.lock.json'
    if not lock.is_file():
        raise ValueError('尚未绑定经确认的锁定模板，禁止执行；请先由维护者完成模板绑定')
    data = json.loads(lock.read_text(encoding='utf-8'))
    if data.get('schema_version') != 1 or data.get('skill_id') != skill_id:
        raise ValueError('模板绑定信息无效')
    path = (root / data['path']).resolve()
    suffix = '.docx' if skill_id == HISTORY.id else '.xlsx'
    if not path.is_relative_to(root / 'assets') or path.suffix.lower() != suffix:
        raise PermissionError('锁定模板必须位于内置资源目录')
    if not path.is_file() or digest(path) != data.get('sha256'):
        raise ValueError('锁定模板缺失或被修改，禁止执行')
    return path


def validate_roles(skill_id, files, roles):
    definitions = INPUT_ROLES[skill_id]
    if not isinstance(roles, dict) or set(roles) - {r[0] for r in definitions}:
        raise ValueError('输入角色不符合所选 Skill')
    by_id = {f['id']: f for f in files}
    if len(by_id) != len(files) or len(set(roles.values())) != len(roles):
        raise ValueError('同一资料不能重复充当多个输入角色')
    for role, label, suffixes, required in definitions:
        if role not in roles and not required:
            continue
        item = by_id.get(roles.get(role))
        if item is None or Path(item['name']).suffix.lower() not in suffixes:
            raise ValueError(f'请指定正确的{label}')
    if set(roles.values()) != set(by_id):
        raise ValueError('每个选定文件都必须分配角色；请取消勾选本轮无关资料')


def artifact_path(store, session_id, run_id, index):
    run = store.run(run_id)
    if run['session'] != session_id:
        raise PermissionError('成果不属于当前会话')
    result = json.loads(run['result'] or '{}')
    items = result.get('artifacts', [])
    if result.get('kind') != 'generation' or not 0 <= index < len(items):
        raise ValueError('成果链接无效')
    item = items[index]
    path = Path(item['path']).resolve()
    root = (store.path.parent / 'runs' / run_id / 'output').resolve()
    if not path.is_relative_to(root) or path.suffix.lower() not in {'.docx', '.xlsx', '.md', '.json'}:
        raise PermissionError('成果路径超出任务范围')
    if not path.is_file() or digest(path) != item['sha256']:
        raise ValueError('成果已修改、移动或删除，请在项目目录核对')
    return path


def execute_generation(store, run_id, snapshot, cancel, progress, *, provider=None, manage_run=True,
                       step_id=None):
    root = validate_business_directory(store.path.parent)
    work = generation_work_directory(root, run_id, step_id)
    with CLIENT_RESOURCES.lease(('output:' + os.path.normcase(str(work)),), cancel):
        return _execute_generation(store, run_id, snapshot, cancel, progress, provider=provider,
                                   manage_run=manage_run, step_id=step_id)


def _execute_generation(store, run_id, snapshot, cancel, progress, *, provider=None, manage_run=True,
                        step_id=None):
    from ..report_review_app.services.task_cancellation import TaskCancelled
    skill_id = snapshot['skill_id']
    roles, files = snapshot.get('input_roles', {}), snapshot['files']
    automatic = snapshot.get('automatic_materials') is True
    if not automatic:
        validate_roles(skill_id, files, roles)
    if (snapshot.get('mode') != 'local_generation'
            or snapshot.get('skill_instructions') != bundle_fingerprint(skill_id)
            or snapshot.get('capabilities') != ['generate_artifacts', 'read_selected_files']):
        raise PermissionError('生成规则或任务能力已变化，请重新确认任务')
    root = validate_business_directory(store.path.parent)
    work = generation_work_directory(root, run_id, step_id, create=True)
    if automatic:
        if provider is None or not snapshot['permissions'].get('call_model'):
            raise PermissionError('资料识别缺少模型授权')
        request_id = run_id if step_id is None else run_id + '-' + hashlib.sha256(step_id.encode()).hexdigest()
        roles, plan = provider.analyze(files, request_id, cancel, progress)
        if cancel.is_set():
            raise TaskCancelled('资料识别已取消，未开始生成')
        if any(digest(Path(f['path'])) != f['sha256'] for f in files):
            raise ValueError('识别过程中资料已变化，请重新添加')
        (work / 'material_analysis.json').write_text(json.dumps(plan, ensure_ascii=False), encoding='utf-8')
        identified = '\n'.join(f"{next(f['name'] for f in files if f['id'] == a['file_id'])}：{a['reason']}"
                               for a in plan['assignments'])
        progress('资料识别完成：' + identified)
        if not roles.get('balance_sheet'):
            feedback = ('资料自动识别结果：\n' + identified + '\n\n'
                        '尚未识别到可确定主体、期间和范围的资产负债表。'
                        '请补充该资料或说明现有文件中哪一部分提供这些信息；没有生成正式工作簿。')
            result = {'kind': 'generation', 'model_called': True, 'ok': False,
                      'artifacts': [], 'feedback': feedback}
            if manage_run:
                store.transition(run_id, 'validating', '资料识别及生成范围检查')
                store.save_result(run_id, result)
                store.transition(run_id, 'failed', '资料已识别，尚需确认范围依据')
            return result
        bound_files = [f for f in files if f['id'] in roles.values()]
        if 'trial_balance' in roles:
            validate_roles(skill_id, bound_files, roles)
        elif any(Path(f['name']).suffix.lower() not in {'.xlsx', '.xls'} for f in bound_files):
            raise ValueError('资料已识别，但当前填报适配器需要可读取的 Excel 来源，不能仅凭识别文本生成')
    sources = work / 'inputs'
    sources.mkdir()
    selected = {}
    template = locked_template(skill_id)
    template_digest = digest(template)
    copied_template = sources / ('template' + template.suffix)
    shutil.copyfile(template, copied_template)
    if digest(copied_template) != template_digest:
        raise ValueError('锁定模板复制校验失败')
    selected['template'] = str(copied_template)
    by_id = {f['id']: f for f in files}
    for role, identity in roles.items():
        if cancel.is_set():
            raise TaskCancelled('任务已取消，未开始生成')
        item = by_id[identity]
        source = Path(item['path'])
        if digest(source) != item['sha256']:
            raise ValueError('资料已变化，请重新添加')
        target = sources / (role + source.suffix.lower())
        shutil.copyfile(source, target)
        if digest(target) != item['sha256']:
            raise ValueError('资料复制校验失败')
        selected[role] = str(target)
    job = work / 'job.json'
    job.write_text(json.dumps({'skill_id': skill_id, 'inputs': selected}, ensure_ascii=False), encoding='utf-8')
    command = ([sys.executable, '--builtin-skill-worker', str(job)] if getattr(sys, 'frozen', False)
               else [sys.executable, '-X', 'utf8', '-m',
                     'asset_based_agent.technical_platform.generation_worker', str(job)])
    environment = dict(os.environ)
    environment['PYTHONPATH'] = str(Path(__file__).resolve().parents[2])
    environment['TEMP'] = environment['TMP'] = str(work)
    environment['PYTHONIOENCODING'] = 'utf-8'
    progress('正在本地生成副本；不上传资料，不调用模型。')
    if cancel.is_set():
        raise TaskCancelled('任务已取消，未启动生成进程')
    progress('等待本地生成资源；可取消排队。')
    office_lease = CLIENT_RESOURCES.lease(('office',), cancel) if skill_id == DETAIL.id else nullcontext()
    with office_lease, (work / 'worker.log').open('w', encoding='utf-8') as log:
        started = time.monotonic()
        process = subprocess.Popen(command, cwd=work, env=environment, stdout=log, stderr=log,
                                   creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        try:
            while process.poll() is None:
                if cancel.wait(0.25):
                    process.terminate()
                    process.wait(timeout=10)
                    break
                if time.monotonic() - started > 1800:
                    raise TimeoutError('本地生成超过30分钟，已停止')
                progress(f'本地生成中，已用 {int(time.monotonic() - started)} 秒；正在执行来源与成果校验。')
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()
    if manage_run:
        store.transition(run_id, 'validating', '重新校验选定原件与生成状态')
    if digest(template) != template_digest or any(digest(Path(f['path'])) != f['sha256'] for f in files):
        raise SourceValidationError('来源文件已变化，本轮成果不得发布')
    status_path = work / 'status.json'
    status = json.loads(status_path.read_text(encoding='utf-8')) if status_path.exists() else {}
    succeeded = not cancel.is_set() and process.returncode == 0 and status.get('ok') is True
    feedback_path = work / 'output/user_feedback.md'
    feedback = feedback_path.read_text(encoding='utf-8') if feedback_path.exists() else '生成未完成，请查看本轮日志；没有发布正式成果。'
    if automatic:
        feedback = '资料自动识别结果：\n' + identified + '\n\n' + feedback
    artifacts = []
    names = (['history_fragment.docx', 'history_events.json', 'history_validation.json']
             if skill_id == HISTORY.id else ['detail_workbook.xlsx', 'completion_status.json',
                                             'delivery_check_report.json', 'execution_scope.json'])
    for name in ([*names, 'user_feedback.md'] if succeeded else ['user_feedback.md']):
        path = work / 'output' / name
        if path.is_file() and path.resolve().is_relative_to(work):
            artifacts.append({'name': name, 'path': str(path), 'sha256': digest(path)})
    result = {'kind': 'generation', 'model_called': automatic, 'artifacts': artifacts,
              'feedback': feedback, 'ok': succeeded}
    if manage_run:
        store.save_result(run_id, result)
        store.transition(run_id, 'cancelled' if cancel.is_set() else 'succeeded' if succeeded else 'failed',
                         '生成与校验通过' if succeeded else '生成被阻断，未发布正式成果')
    return result
