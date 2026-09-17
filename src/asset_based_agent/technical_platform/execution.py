"""Fixed read-only plan and execution harness for versioned platform tasks."""

import json
from hashlib import sha256

from ..report_review_app.services.task_cancellation import TaskCancelled
from .context import build_context, model_request
from .execution_plan import ExecutionPlan
from .file_scope import freeze_scope
from .permissions import PermissionService
from .planner import single_adapter_plan
from .skills import BUILTINS, DETAIL, GENERATORS, REVIEW, preflight
from .store import now
from .task_spec import read_snapshot, snapshot_identity


def execute_task(store, run_id, cancel, progress, *, provider=None, output=None, client=None):
    phase = "planning"
    # A failed claim must not enter the failure handler and fail another executor's run.
    run = store.claim_run(run_id)
    try:
        if cancel.is_set():
            store.transition(run_id, "cancelled", "planning: 执行前取消")
            return {"kind": "cancelled"}
        snapshot = read_snapshot(json.loads(run["snapshot"]))
        if snapshot["schema_version"] != 2:
            raise PermissionError("历史任务缺少明确授权，请重新提交任务")
        if 'execution_plan' not in snapshot or 'file_scope' not in snapshot:
            raise PermissionError('任务缺少计划或文件范围，请重新提交任务')
        permissions = PermissionService(store)
        permissions.verify(run_id)
        snapshot_identity(snapshot)
        session = store.session(run["session"])
        if (snapshot.get("owner") != store.owner
                or snapshot.get("task_id") != run_id
                or snapshot.get("session_id") != run["session"]
                or snapshot.get("project_id") != session["project"]):
            raise PermissionError("任务身份或归属不匹配")
        if snapshot.get('mode') == 'compound':
            from .compound_task import execute_compound_claimed
            if provider is not None:
                raise PermissionError('组合任务使用独立步骤模型，不接受单任务provider')
            phase = 'execution'
            return execute_compound_claimed(store, run_id, snapshot, cancel, progress, client=client, output=output)
        skill = {s.id: s for s in BUILTINS}.get(snapshot.get("skill_id"))
        if skill is None or snapshot.get("skill_version") != skill.version:
            raise PermissionError("Skill 版本不匹配，请重新提交")
        external = snapshot.get('external_skill')
        if external:
            from .skill_installation import SkillInstallation
            manager = SkillInstallation(store)
            package = manager.load(external['id'], external['version'])
            enabled = any(v['skill_id'] == external['id'] and v['version'] == external['version'] and v['enabled'] for v in manager.list_versions())
            if not enabled or not package.ready or package.sha256 != external['sha256'] or package.manifest['adapter'] != skill.id:
                raise PermissionError('外部Skill已停用或版本变化，请重新提交')
        remote = skill == REVIEW
        generation = skill in GENERATORS
        automatic = skill == DETAIL and snapshot.get('automatic_materials') is True
        expected = {"read_selected_files": True, "modify_originals": False,
                    "call_model": remote or automatic, "upload_raw_files": False,
                    **({'generate_artifacts': True} if generation else {})}
        if snapshot.get("permissions") != expected:
            raise PermissionError("任务权限与只读计划不匹配")
        gates = (["source_evidence", "output_validation", "original_hash_unchanged"] if generation
                 else ["visible_content_only", "original_hash_unchanged"])
        if snapshot.get("acceptance_gates") != gates:
            raise PermissionError("任务验收门禁不完整")
        available = {f["id"]: f for f in store.files(session["project"])}
        files = snapshot.get("files", [])
        if not files or any(available.get(f["id"]) != f for f in files):
            raise PermissionError("选定文件不属于项目或版本已变化")
        if snapshot.get("selected_files") != [
            {"id": f["id"], "version": f["sha256"], "sha256": f["sha256"]} for f in files
        ]:
            raise PermissionError("任务文件版本记录不一致")
        if 'execution_plan' in snapshot:
            plan = ExecutionPlan.model_validate(snapshot['execution_plan'])
            expected_plan = single_adapter_plan(snapshot_identity(snapshot), skill, files,
                                                snapshot['skill_rules_sha256'])
            if plan != expected_plan:
                raise PermissionError('执行计划与本轮任务不一致，请重新确认')
        if 'file_scope' in snapshot:
            scope = snapshot['file_scope']
            expected_scope = freeze_scope(store, run['session'], targets=files, revision=1).to_snapshot()
            if (not isinstance(scope, dict) or type(scope.get('revision')) is not int
                    or type(scope.get('schema_version')) is not int or scope != expected_scope):
                raise PermissionError('任务范围与选定文件或会话不一致，请重新确认')
        if (remote or automatic) != (provider is not None):
            raise PermissionError("模型调用方式与计划不匹配")
        if provider is not None and (provider.model_id != snapshot.get("model")
                    or provider.skill_instructions != snapshot.get("skill_instructions")
                    or sha256(provider.skill_instructions.encode("utf-8")).hexdigest()
                    != snapshot.get("skill_rules_sha256")):
            raise PermissionError("模型或规则版本与任务快照不匹配")
        phase = "context"
        context = build_context(store, run["session"], snapshot["user_request"])
        snapshot["execution_context"] = context
        # Persist what was actually selected; retracted memories are not replayed.
        with store.connect() as db:
            updated = db.execute(
                "UPDATE runs SET snapshot=? WHERE id=? AND state='running'",
                (json.dumps(snapshot, ensure_ascii=False), run_id),
            )
            if updated.rowcount != 1:
                raise ValueError("任务状态已变化")
        if provider is not None:
            provider.user_request = model_request(snapshot["user_request"], context)
            provider.cancel_event = cancel
        phase = "execution"
        permissions.verify(run_id)
        from .adapters.generation import GenerationAdapter
        from .adapters.review import ReviewAdapter
        from .harness import _execute_claimed_plan
        from .tool_dispatcher import ToolDispatcher
        adapter = (GenerationAdapter(store, run_id, progress=progress, provider=provider) if generation
                   else ReviewAdapter(store, run_id, progress=progress, provider=provider,
                                      output=output, review_function=preflight))
        status = _execute_claimed_plan(store, run_id, plan,
                                       ToolDispatcher({plan.steps[0].tool: adapter}), cancel,
                                       raise_errors=True)
        if status == 'cancelled':
            return {'kind': 'cancelled'}
        if status == 'failed' and generation and store.run(run_id)['result']:
            return json.loads(store.run(run_id)['result'])
        if status != 'succeeded':
            raise RuntimeError('任务尚未完成，请核对执行状态；不要重复提交')
        return json.loads(store.run(run_id)['result'])
    except TaskCancelled:
        if store.run(run_id)['state'] in {'running', 'validating'}:
            store.transition(run_id, 'cancelled', '用户停止；不再接收结果或继续本地生成')
        return {'kind': 'cancelled'}
    except Exception as exc:
        state = store.run(run_id)["state"]
        if state == "validating" or getattr(exc, 'stage', None) == 'validation':
            phase = "validation"
        detail = f"{phase}: {type(exc).__name__}"
        if state in {"queued", "running", "validating"}:
            store.transition(run_id, "failed", detail)
        else:
            with store.connect() as db:
                db.execute("INSERT INTO events(run,state,detail,created) VALUES(?,?,?,?)",
                           (run_id, state, detail, now()))
        raise
