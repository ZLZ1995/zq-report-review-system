"""Versioned local task contracts; snapshots are records, never fresh authorization."""

from copy import deepcopy
from dataclasses import dataclass
from hashlib import sha256
from uuid import uuid4

from .context import build_context
from .execution_contracts import TaskIdentity
from .file_scope import freeze_scope
from .planner import single_adapter_plan
from .release_info import local_release
from .skills import BUILTINS, DETAIL, GENERATORS, REVIEW, SkillSpec
from .store import PlatformStore


@dataclass(frozen=True)
class TaskSpec:
    _snapshot: dict

    def to_snapshot(self) -> dict:
        return deepcopy(self._snapshot)


def build_task_spec(
    store: PlatformStore, session_id: str, user_request: str, skill: SkillSpec,
    files: list[dict], *, model: str | None = None, instructions: str = "",
    input_roles: dict | None = None, generation_confirmed: bool = False,
) -> TaskSpec:
    session = store.session(session_id)
    if skill not in BUILTINS:
        raise PermissionError("当前只允许已注册的只读审核任务")
    remote = skill.id == REVIEW.id
    generation = skill in GENERATORS
    automatic = skill == DETAIL and input_roles is None
    if generation:
        from .generation import bundle_fingerprint, validate_roles
        from .project_catalog import validate_business_directory
        if generation_confirmed is not True:
            raise PermissionError('生成新文件需要本轮明确确认；不授予原件修改权限')
        validate_business_directory(store.path.parent)
        if automatic:
            if not model:
                raise ValueError('资料自动识别需要先登录模型服务并选择模型')
            if len(files) > 20:
                raise ValueError('单轮最多分析20个文件，请缩小本轮范围')
        else:
            validate_roles(skill.id, files, input_roles or {})
        instructions = bundle_fingerprint(skill.id)
    if not user_request.strip() or not files:
        raise ValueError("任务要求及选定文件不能为空")
    if len(user_request.strip()) > 12000:
        raise ValueError("本轮要求超过 12000 字符，请缩短后提交")
    if remote and (not model or not instructions.strip()):
        raise ValueError("模型审核需要模型及已加载的规则")
    scope = freeze_scope(store, session_id, targets=files, revision=1)
    context = build_context(store, session_id, user_request.strip())
    identity = TaskIdentity(owner=store.owner, project_id=session['project'], session_id=session_id,
                            task_id=uuid4().hex, request_id=uuid4().hex)
    return TaskSpec(deepcopy({
        **identity.model_dump(),
        "schema_version": 2, "requires_authorization": True,
        "execution_plan": single_adapter_plan(identity, skill, files,
                                               sha256(instructions.encode('utf-8')).hexdigest()).model_dump(),
        "user_request": user_request.strip(), "release": local_release(),
        "skill_id": skill.id, "skill_version": skill.version,
        "skill_rules_sha256": sha256(instructions.encode("utf-8")).hexdigest(),
        "skill_instructions": instructions, "capabilities": sorted(skill.capabilities),
        "files": files,
        "file_scope": scope.to_snapshot(),
        "selected_files": [{"id": f["id"], "version": f["sha256"],
                            "sha256": f["sha256"]} for f in files],
        "context": context, "memory_ids": context["memory_ids"],
        "mode": "local_generation" if generation else "remote_review" if remote else "local_preflight",
        "model": model if remote or automatic else None,
        "permissions": {"read_selected_files": True, "modify_originals": False,
                        "call_model": remote or automatic, "upload_raw_files": False,
                        **({'generate_artifacts': True} if generation else {})},
        **({'input_roles': input_roles, 'automatic_materials': automatic} if generation else {}),
        "acceptance_gates": (["source_evidence", "output_validation", "original_hash_unchanged"]
                             if generation else ["visible_content_only", "original_hash_unchanged"]),
    }))


def read_snapshot(snapshot: dict) -> dict:
    """Adapt history for display only; legacy grants are deliberately discarded."""
    result = deepcopy(snapshot)
    version = result.get("schema_version", 0)
    if type(version) is not int or version not in (0, 1, 2):
        raise ValueError("不支持的任务快照版本")
    result["schema_version"] = version
    if version < 2:
        result["permissions"] = {}
        result["requires_confirmation"] = True
    return result


def snapshot_identity(snapshot: dict) -> TaskIdentity:
    """v1 records predating request IDs retain their task ID as trace identity."""
    if type(snapshot.get('schema_version')) is not int or snapshot['schema_version'] not in (1, 2):
        raise ValueError('Unsupported task snapshot identity version')
    return TaskIdentity.model_validate({
        'schema_version': 1, 'owner': snapshot.get('owner'),
        'project_id': snapshot.get('project_id'), 'session_id': snapshot.get('session_id'),
        'task_id': snapshot.get('task_id'),
        'request_id': snapshot.get('request_id', snapshot.get('task_id')),
    })
