"""Compile and revalidate a complete task before any step can execute."""
import json
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

from ..agent_contracts import PlanningRequest, PlanProposal
from .context import build_context
from .execution_contracts import TaskIdentity
from .execution_plan import ExecutionPlan
from .file_scope import freeze_scope
from .generation import bundle_fingerprint
from .planner import compile_proposal
from .release_info import local_release
from .skills import BUILTINS, DETAIL, GENERATORS, HISTORY, REVIEW
from .task_spec import TaskSpec, snapshot_identity


def _fields(store, session_id, payload, proposal, files, identity, revision):
    request = PlanningRequest.model_validate(payload)
    proposal = PlanProposal.model_validate(proposal)
    session = store.session(session_id)
    if (identity.owner != store.owner or identity.session_id != session_id
            or identity.project_id != session['project']):
        raise PermissionError('Compound task identity mismatch')
    available = {f['id']: f for f in store.files(session['project'])}
    by_id = {f['id']: f for f in files}
    if (len(by_id) != len(files) or set(by_id) != {f.id for f in request.request.files}
            or any(available.get(key) != value for key, value in by_id.items())):
        raise PermissionError('Planning files changed or are outside the project')
    for file in request.request.files:
        if file.model_dump() != {key: by_id[file.id][key] for key in ('id', 'name', 'sha256')}:
            raise PermissionError('Planning file version changed')
    understanding = request.understanding
    builtin = {s.id: s for s in BUILTINS}
    candidates = {s.id: s for s in request.request.skills}
    instructions, bindings = {}, {}
    for skill_id in understanding.skill_ids:
        adapter = candidates[skill_id].adapter
        package = None
        if skill_id in builtin:
            if adapter != skill_id:
                raise PermissionError('Builtin skill adapter mismatch')
        else:
            from .skill_installation import SkillInstallation
            with store.connect() as db:
                if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='installed_skills'").fetchone() is None:
                    raise PermissionError('外部Skill尚未安装')
            manager = SkillInstallation(store, initialize=False)
            enabled = [v for v in manager.list_versions() if v['skill_id'] == skill_id and v['enabled']]
            if len(enabled) != 1:
                raise PermissionError('外部Skill未启用或版本不唯一')
            package = manager.load(skill_id, enabled[0]['version'])
            if not package.ready or package.manifest['adapter'] != adapter:
                raise PermissionError('外部Skill依赖或适配器已变化')
            bindings[skill_id] = {'id': skill_id, 'version': package.manifest['version'], 'sha256': package.sha256}
        skill = builtin[adapter]
        instructions[skill_id] = (bundle_fingerprint(skill_id) if skill in GENERATORS else
                                  Path(__file__).with_name('review_rules.txt').read_text('utf-8')
                                  if skill == REVIEW else '')
        if package is not None:
            instructions[skill_id] += '\n外部专业规则（不扩大权限）：\n' + package.instructions
    plan = compile_proposal(request.request, understanding, proposal, identity,
                            rules_hashes={key: sha256(value.encode()).hexdigest()
                                          for key, value in instructions.items()}, revision=revision)
    configs = {}
    selected_skills = {s.step_id: s.skill_id for s in proposal.steps}
    for step in plan.steps:
        skill = builtin[step.skill_id]
        if skill in GENERATORS and step.reference_inputs:
            raise ValueError('Generator reference roles are not supported by its input contract')
        roles = None
        if skill == HISTORY:
            if len(step.inputs) != 1:
                raise ValueError('工商生成步骤需要唯一的工商变更Excel来源')
            roles = {'source_excel': step.inputs[0]}
        if skill == DETAIL and len(step.inputs) > 20:
            raise ValueError('单步资料识别最多20个文件')
        selected_skill = selected_skills[step.step_id]
        configs[step.step_id] = {'skill_instructions': instructions[selected_skill],
                                'input_roles': roles, 'automatic_materials': skill == DETAIL}
        if selected_skill in bindings:
            configs[step.step_id]['external_skill'] = bindings[selected_skill]
    call_model = any(s.skill_id in {REVIEW.id, DETAIL.id} for s in plan.steps)
    creates_files = any(builtin[s.skill_id] in GENERATORS for s in plan.steps)
    selected = [by_id[ref] for ref in [*understanding.targets, *understanding.references]]
    scope = freeze_scope(store, session_id, targets=[by_id[i] for i in understanding.targets],
                         references=[by_id[i] for i in understanding.references],
                         excluded=[by_id[i] for i in understanding.excluded], revision=revision)
    return {
        'mode': 'compound', 'execution_plan': plan.model_dump(), 'step_configs': configs,
        'planning_request': request.model_dump(), 'plan_proposal': proposal.model_dump(),
        'planning_files': files, 'files': selected, 'file_scope': scope.to_snapshot(),
        'selected_files': [{'id': f['id'], 'sha256': f['sha256'], 'version': f['sha256']} for f in selected],
        'user_request': request.request.prompt, 'model': request.request.model_id if call_model else None,
        'permissions': {'read_selected_files': True, 'modify_originals': False,
                        'upload_raw_files': False, 'call_model': call_model,
                        **({'generate_artifacts': True} if creates_files else {})},
    }


def build_compound_task_spec(store, session_id, payload, proposal, files, *, revision):
    request = PlanningRequest.model_validate(payload)
    identity = TaskIdentity(owner=store.owner, project_id=store.session(session_id)['project'],
                            session_id=session_id, task_id=uuid4().hex, request_id=request.request.request_id)
    fields = _fields(store, session_id, request.model_dump(), proposal, files, identity, revision)
    context = build_context(store, session_id, fields['user_request'])
    return TaskSpec(deepcopy({**identity.model_dump(), 'schema_version': 2, 'requires_authorization': True,
                              **fields, 'context': context, 'memory_ids': context['memory_ids'],
                              'release': local_release()}))


def execute_compound_claimed(store, run_id, snapshot, cancel, progress, *, client=None, output=None):
    from .adapters.generation import GenerationAdapter
    from .adapters.review import ReviewAdapter
    from .harness import _execute_claimed_plan
    from .tool_dispatcher import ToolDispatcher

    identity = snapshot_identity(snapshot)
    plan = ExecutionPlan.model_validate(snapshot['execution_plan'])
    fields = _fields(store, identity.session_id, snapshot['planning_request'], snapshot['plan_proposal'],
                      snapshot['planning_files'], identity, plan.revision)
    if any(snapshot.get(key) != value for key, value in fields.items()):
        raise PermissionError('Compound snapshot differs from its verified compilation')
    if snapshot['permissions']['call_model'] and (client is None or not getattr(client, 'access_token', None)):
        raise PermissionError('模型步骤需要有效登录，未启动任何步骤')
    context = build_context(store, identity.session_id, snapshot['user_request'])
    snapshot = {**snapshot, 'execution_context': context}
    with store.connect() as db:
        updated = db.execute("UPDATE runs SET snapshot=? WHERE id=? AND state='running'",
                             (json.dumps(snapshot, ensure_ascii=False), run_id))
        if updated.rowcount != 1:
            raise ValueError('Task state changed')
    adapters = {}
    for step in plan.steps:
        config = snapshot['step_configs'][step.step_id]
        provider = None
        if step.skill_id == REVIEW.id:
            from ..report_review_app.services.remote_review_llm import RemoteReviewLlm
            provider = RemoteReviewLlm(client, model_id=snapshot['model'],
                                       skill_instructions=config['skill_instructions'])
        elif step.skill_id == DETAIL.id:
            from .material_analysis import MaterialAnalysisProvider
            provider = MaterialAnalysisProvider(client, snapshot['model'], config['skill_instructions'])
        adapters[step.step_id] = (GenerationAdapter(store, run_id, progress=progress, provider=provider)
                                  if step.skill_id in {s.id for s in GENERATORS}
                                  else ReviewAdapter(store, run_id, progress=progress, provider=provider, output=output))
    def dispatch(step, dependencies, cancellation):
        progress(f'正在执行步骤：{step.goal or step.step_id}')
        return adapters[step.step_id](step, dependencies, cancellation)
    status = _execute_claimed_plan(store, run_id, plan,
                                   ToolDispatcher({s.tool: dispatch for s in plan.steps}), cancel, raise_errors=True)
    if status == 'cancelled':
        return {'kind': 'cancelled'}
    if status != 'succeeded':
        raise RuntimeError('组合任务未完成，请核对步骤状态；不要重复提交')
    return json.loads(store.run(run_id)['result'])
