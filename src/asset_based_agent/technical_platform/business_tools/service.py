"""业务 Run 服务：权限回执核验、幂等、取消登记与有界输出。

本服务驱动与现有 UI 完全相同的 build_task_spec → start_run → execute_task
链路；不复制任何业务规则，所有硬门禁仍由原链路执行。
"""
import json
import threading
from collections import deque
from hashlib import sha256
from pathlib import Path

from ..agent_core.errors import (
    ToolFailed,
    ToolInvalidArguments,
    ToolPermissionDenied,
)
from ..annotations import generate_annotations
from ..execution import execute_task
from ..skills import BUILTINS, DETAIL, GENERATORS, REVIEW, digest
from ..task_spec import build_task_spec

SUMMARY_LIMIT = 2000
MAX_WARNINGS = 20
MAX_FACTS = 50
MAX_RECORDS = 50

INTERNAL_ARTIFACT_NAMES = frozenset({
    'completion_status.json', 'delivery_check_report.json',
    'execution_scope.json', 'material_analysis.json', 'user_feedback.md'})


class BusinessRunService:
    """绑定一个业务会话的 Run 执行服务；provider 由工厂注入（S14 接线）。"""

    def __init__(self, store, session_id, *, provider_factory=None):
        store.session(session_id)
        self.store = store
        self.session_id = session_id
        self._provider_factory = provider_factory
        self._active = {}
        self._pending_providers = {}

    # ------------------------------------------------------------ helpers

    def _project_id(self):
        return self.store.session(self.session_id)['project']

    def _file_rows(self, file_ids):
        rows = {f['id']: f for f in self.store.files(self._project_id())}
        if any(fid not in rows for fid in file_ids):
            raise ToolInvalidArguments('文件不属于本项目，请先 inspect_project_files 核对')
        return rows

    def _run_for_session(self, run_id):
        try:
            run = self.store.run(run_id)
        except PermissionError:
            raise ToolFailed('任务不存在或不属于当前用户') from None
        if run['session'] != self.session_id:
            raise ToolFailed('任务不属于当前会话')
        return run

    def active_runs(self):
        return dict(self._active)

    # -------------------------------------------------------- inspection

    def inspect_files(self):
        return {'files': [
            {'id': f['id'], 'name': f['name'], 'size': f['size'], 'sha256': f['sha256']}
            for f in self.store.files(self._project_id())]}

    def analyze_roles(self, file_ids):
        from ...report_review_app.services.file_role_service import classify_file_role
        file_ids = list(file_ids)
        if not file_ids:
            raise ToolInvalidArguments('file_ids 不能为空')
        rows = self._file_rows(file_ids)
        return {'files': [
            {'id': fid, 'name': rows[fid]['name'],
             'suffix': Path(rows[fid]['name']).suffix.lower(),
             'role': classify_file_role(Path(rows[fid]['path'])).value}
            for fid in file_ids]}

    # ----------------------------------------------------------- execute

    def queue_skill_plan(self, *, skill_id, skill_version, skill_hash,
                         target_file_ids, reference_file_ids, user_goal,
                         confirmed_facts, permission_receipt, idempotency_key,
                         input_roles=None, instructions=''):
        """校验并入队；幂等键命中已有 run 时直接返回该 run id。"""
        replay = self._find_by_idempotency_key(idempotency_key)
        if replay is not None:
            return replay
        skill = {s.id: s for s in BUILTINS}.get(skill_id)
        if skill is None:
            raise ToolInvalidArguments(f'未注册的 Skill: {skill_id}')
        if skill_version != skill.version:
            raise ToolPermissionDenied('Skill 版本与本地注册不一致，请刷新资源后重试')
        generation = skill in GENERATORS
        instructions = self._resolve_instructions(skill, generation, instructions)
        expected = sha256(instructions.encode('utf-8')).hexdigest()
        if skill_hash != expected:
            raise ToolPermissionDenied('Skill 规则指纹与本地锁定版本不一致')
        needs_model = skill == REVIEW or (skill == DETAIL and input_roles is None)
        granted = self._granted(permission_receipt)
        required = {'read_selected_files'}
        if generation:
            required.add('generate_artifacts')
        if needs_model:
            required.add('call_model')
        missing = sorted(required - granted)
        if missing:
            raise ToolPermissionDenied(f'缺少权限授予：{", ".join(missing)}')
        provider = None
        if needs_model:
            if self._provider_factory is None:
                raise ToolPermissionDenied('该 Skill 需要模型服务，当前会话尚未接线')
            provider = self._provider_factory(skill_id, instructions)
        target_file_ids = list(target_file_ids)
        reference_file_ids = list(reference_file_ids)
        if not target_file_ids:
            raise ToolInvalidArguments('至少需要指定一个目标文件')
        rows = self._file_rows([*target_file_ids, *reference_file_ids])
        files = [rows[fid] for fid in [*target_file_ids, *reference_file_ids]]
        try:
            spec = build_task_spec(
                self.store, self.session_id, user_goal, skill, files,
                model=None, instructions=instructions, input_roles=input_roles,
                generation_confirmed=generation)
        except PermissionError as exc:
            raise ToolPermissionDenied(str(exc)) from None
        except (ValueError, OSError) as exc:
            raise ToolInvalidArguments(str(exc)) from None
        snapshot = spec.to_snapshot()
        snapshot['agent_idempotency_key'] = str(idempotency_key)
        snapshot['agent_confirmed_facts'] = [
            str(fact)[:500] for fact in list(confirmed_facts)[:MAX_FACTS]]
        snapshot['agent_reference_file_ids'] = reference_file_ids
        run_id = self.store.start_run(self.session_id, snapshot)
        # 与可信 UI 相同的显式确认：Agent 侧权限回执核验通过后，
        # 以同一快照登记平台级授权回执（execution_authorizations）。
        from ..permissions import PermissionService
        PermissionService(self.store).authorize(run_id, snapshot, confirmed=True)
        if provider is not None:
            self._pending_providers[run_id] = provider
        return run_id

    def execute_skill_plan(self, *, cancel_event=None, **kwargs):
        run_id = self.queue_skill_plan(**kwargs)
        if self.store.run(run_id)['state'] != 'queued':
            return self._output(run_id)  # 幂等重放：不重复执行
        return self.drive_run(run_id, cancel_event or threading.Event())

    def drive_run(self, run_id, cancel_event):
        provider = self._pending_providers.pop(run_id, None)
        progress = deque(maxlen=50)  # 进度只进有界缓冲，不进入工具输出
        self._active[run_id] = cancel_event
        try:
            execute_task(self.store, run_id, cancel_event, progress.append,
                         provider=provider)
        except Exception as exc:  # noqa: BLE001 - 业务边界统一映射为可定位的失败
            raise ToolFailed(
                f'业务执行失败（run {run_id[:8]}…）：{type(exc).__name__}；'
                '失败原因已记录，可用 query_business_run 定位该 run。') from None
        finally:
            self._active.pop(run_id, None)
        return self._output(run_id)

    def _find_by_idempotency_key(self, key):
        if not str(key).strip():
            raise ToolInvalidArguments('idempotency_key 不能为空')
        for run in self.store.runs(self.session_id):
            try:
                snapshot = json.loads(run['snapshot'])
            except (TypeError, ValueError):
                continue
            if snapshot.get('agent_idempotency_key') == str(key):
                return run['id']
        return None

    @staticmethod
    def _granted(receipt):
        if not isinstance(receipt, dict) \
                or not isinstance(receipt.get('granted'), (list, tuple)):
            raise ToolPermissionDenied('缺少有效权限回执（permission_receipt.granted）')
        return {str(item) for item in receipt['granted']}

    @staticmethod
    def _resolve_instructions(skill, generation, instructions):
        if generation:
            from ..generation import bundle_fingerprint
            try:
                return bundle_fingerprint(skill.id)
            except (ValueError, OSError) as exc:
                raise ToolFailed(f'内置 Skill 资源不可用：{exc}') from None
        if skill == REVIEW:
            if not str(instructions).strip():
                raise ToolInvalidArguments('模型审核需要已加载的审核规则')
            return str(instructions).strip()
        return ''

    # ----------------------------------------------------- query / cancel

    def query_run(self, run_id):
        self._run_for_session(run_id)
        return self._output(run_id)

    def cancel_run(self, run_id):
        run = self._run_for_session(run_id)
        if run['state'] == 'queued':
            self.store.transition(run_id, 'cancelled', 'Agent 取消：执行前停止')
            return {'run_id': run_id, 'state': 'cancelled'}
        event = self._active.get(run_id)
        if run['state'] in {'running', 'validating'} and event is not None:
            event.set()
            return {'run_id': run_id, 'state': 'cancelling'}
        raise ToolFailed(f'任务当前状态（{run["state"]}）不可取消')

    # --------------------------------------------------------- artifacts

    def list_final_artifacts(self, run_id):
        run = self._run_for_session(run_id)
        result = json.loads(run['result'] or '{}')
        return {'run_id': run_id, 'state': run['state'],
                'artifacts': self._artifact_refs(result)}

    # ---------------------------------------------------------- annotate

    def annotate(self, run_id, selected, directory):
        self._run_for_session(run_id)
        try:
            selected = sorted({int(n) for n in selected})
        except (TypeError, ValueError):
            raise ToolInvalidArguments('selected 必须是问题序号列表') from None
        if not selected:
            raise ToolInvalidArguments('selected 不能为空')
        try:
            records, artifacts = generate_annotations(
                self.store, run_id, selected, Path(directory))
        except (ValueError, OSError, PermissionError) as exc:
            raise ToolFailed(f'标注未完成：{exc}') from None
        refs = [{'name': Path(path).name, 'sha256': digest(Path(path))}
                for path in artifacts]
        return {'run_id': run_id, 'records': records[:MAX_RECORDS], 'artifacts': refs}

    # ------------------------------------------------------------ output

    def _output(self, run_id):
        run = self.store.run(run_id)
        result = json.loads(run['result'] or '{}')
        state = run['state']
        return {
            'run_id': run_id,
            'state': state,
            'summary': self._summarize(state, result),
            'artifacts': self._artifact_refs(result),
            'validation_status': 'passed' if state == 'succeeded' else state,
            'warnings': self._warnings(result),
            'follow_up_capabilities': self._follow_ups(result),
        }

    @staticmethod
    def _summarize(state, result):
        kind = result.get('kind')
        if state == 'cancelled':
            text = '任务已取消；未交付任何成果。'
        elif kind == 'preflight':
            files = result.get('files', [])
            lines = [f'预检完成：解析 {len(files)} 个文件，未调用模型。']
            for item in files[:MAX_WARNINGS]:
                line = f"- {item.get('name')}：{item.get('chunks')} 个片段"
                if item.get('warnings'):
                    line += '；警告：' + '；'.join(str(w) for w in item['warnings'])
                lines.append(line)
            text = '\n'.join(lines)
        elif kind == 'review':
            text = f"审核完成：{len(result.get('issues', []))} 条意见；原件未修改。"
        elif kind == 'generation':
            text = str(result.get('feedback') or '生成完成，成果已通过校验。')
        elif state == 'failed':
            text = '任务失败；未交付任何成果。'
        else:
            text = f'任务状态：{state}'
        return text[:SUMMARY_LIMIT]

    @staticmethod
    def _warnings(result):
        warnings = []
        for item in result.get('files', []) or []:
            warnings.extend(str(w) for w in item.get('warnings', []) or [])
        return warnings[:MAX_WARNINGS]

    @staticmethod
    def _follow_ups(result):
        follow = ['query_business_run']
        kind = result.get('kind')
        if kind == 'review':
            follow.append('annotate_reviewed_files')
        if kind == 'generation':
            follow.append('list_final_artifacts')
        return follow

    @staticmethod
    def _artifact_refs(result):
        refs = []
        for index, item in enumerate(result.get('artifacts', []) or []):
            name = str(item.get('name', ''))
            if item.get('visibility') != 'user' or name in INTERNAL_ARTIFACT_NAMES:
                continue
            ref = {'index': index, 'name': name, 'sha256': str(item.get('sha256', ''))}
            if item.get('display_name'):
                ref['display_name'] = str(item['display_name'])
            refs.append(ref)
        return refs
