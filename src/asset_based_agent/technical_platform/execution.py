"""Fixed read-only plan and execution harness for versioned platform tasks."""

import json
from hashlib import sha256

from .context import build_context, model_request
from .skills import BUILTINS, GENERATORS, REVIEW, preflight
from .store import now
from .task_spec import read_snapshot


def execute_task(store, run_id, cancel, progress, *, provider=None, output=None):
    phase = "planning"
    # A failed claim must not enter the failure handler and fail another executor's run.
    run = store.claim_run(run_id)
    try:
        if cancel.is_set():
            store.transition(run_id, "cancelled", "planning: 执行前取消")
            return {"kind": "cancelled"}
        snapshot = read_snapshot(json.loads(run["snapshot"]))
        if snapshot["schema_version"] != 1:
            raise PermissionError("历史任务缺少明确授权，请重新提交任务")
        session = store.session(run["session"])
        if (snapshot.get("owner") != store.owner
                or snapshot.get("task_id") != run_id
                or snapshot.get("session_id") != run["session"]
                or snapshot.get("project_id") != session["project"]):
            raise PermissionError("任务身份或归属不匹配")
        skill = {s.id: s for s in BUILTINS}.get(snapshot.get("skill_id"))
        if skill is None or snapshot.get("skill_version") != skill.version:
            raise PermissionError("Skill 版本不匹配，请重新提交")
        remote = skill == REVIEW
        generation = skill in GENERATORS
        expected = {"read_selected_files": True, "modify_originals": False,
                    "call_model": remote, "upload_raw_files": False,
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
        if remote != (provider is not None):
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
        phase = "execution"
        if generation:
            from .generation import execute_generation
            return execute_generation(store, run_id, snapshot, cancel, progress)
        return preflight(store, run_id, cancel, progress, provider=provider, output=output,
                         claimed=True)
    except Exception as exc:
        state = store.run(run_id)["state"]
        if state == "validating":
            phase = "validation"
        detail = f"{phase}: {type(exc).__name__}"
        if state in {"queued", "running", "validating"}:
            store.transition(run_id, "failed", detail)
        else:
            with store.connect() as db:
                db.execute("INSERT INTO events(run,state,detail,created) VALUES(?,?,?,?)",
                           (run_id, state, detail, now()))
        raise
