"""Local trusted compiler for declarative workflow plans.

Compilation binds a proposed plan to the frozen TurnEnvelope: scope, tool
whitelist, original-write red line, cross-project paths and budgets are all
decided here. Compilation is not authorization and runs no business tool.
"""
from __future__ import annotations

import json
import re
from hashlib import sha256

from pydantic import Field

from ..agent_contracts import Identifier, Record
from .turn_context import TurnEnvelope, envelope_hash
from .workflow_plan import NodeInput, WorkflowNode, WorkflowPlan

MAX_NODE_TOKEN_BUDGET = 200_000
_ABSOLUTE_PATH = re.compile(r'^(?:[A-Za-z]:[\\/]|/|\\\\)')


class CompiledStep(Record):
    node_id: Identifier
    type: str
    skill_id: str | None = None
    resource: str | None = None
    client_job_id: str | None = None
    inputs: tuple[tuple[str, str], ...] = ()
    depends_on: tuple[Identifier, ...] = ()
    token_budget: int = Field(ge=0, le=MAX_NODE_TOKEN_BUDGET)


class CompiledWorkflow(Record):
    compile_hash: str = Field(pattern=r'^[0-9a-f]{64}$')
    envelope_hash: str = Field(pattern=r'^[0-9a-f]{64}$')
    plan_id: Identifier
    revision: int = Field(ge=1)
    steps: tuple[CompiledStep, ...]


def compile_plan(plan, *, envelope, allowed_tools) -> CompiledWorkflow:
    plan = WorkflowPlan.model_validate(
        plan.model_dump() if isinstance(plan, WorkflowPlan) else plan)
    envelope = TurnEnvelope.model_validate(envelope.model_dump())
    if plan.envelope_hash != envelope_hash(envelope):
        raise ValueError('计划与本轮信封不一致，可能来自过期理解')
    selected = {item.id for item in envelope.selected_attachment_versions}
    by_id = {node.node_id: node for node in plan.nodes}
    allowed = set(allowed_tools)

    def ancestors(node_id):
        seen, pending = set(), list(by_id[node_id].depends_on)
        while pending:
            parent = pending.pop()
            if parent not in seen:
                seen.add(parent)
                pending.extend(by_id[parent].depends_on)
        return seen

    steps = []
    for node in plan.nodes:
        config = dict(node.config)
        if config.get('write_target') == 'original':
            raise ValueError('原始业务文件只读，节点不得写入原件')
        budget = config.get('token_budget', 0)
        if type(budget) is not int or not 0 <= budget <= MAX_NODE_TOKEN_BUDGET:
            raise ValueError('节点预算超出许可范围')
        skill_id = config.get('skill_id')
        if node.type == 'run_skill' and (not isinstance(skill_id, str)
                                         or skill_id not in allowed):
            raise ValueError('节点请求了未登记的工具或能力')
        for item in node.inputs:
            if item.kind == 'attachment' and item.ref not in selected:
                raise ValueError('节点输入包含本轮未选定的附件')
            if item.kind == 'node_output' and item.ref not in ancestors(node.node_id):
                raise ValueError('节点输入缺少上游产出')
            if item.kind == 'literal' and _ABSOLUTE_PATH.match(item.ref):
                raise ValueError('节点输入包含跨项目绝对路径')
        resource = config.get('resource')
        if resource is not None and (not isinstance(resource, str) or len(resource) > 128):
            raise ValueError('资源锁标识无效')
        client_job_id = config.get('client_job_id')
        if client_job_id is not None and (not isinstance(client_job_id, str)
                                          or len(client_job_id) > 128):
            raise ValueError('客户端任务标识无效')
        steps.append((node, skill_id if isinstance(skill_id, str) else None, budget,
                      resource, client_job_id))

    ordered = []
    done: set[str] = set()
    while len(done) != len(steps):
        for node, skill_id, budget, resource, client_job_id in steps:
            if node.node_id not in done and set(node.depends_on) <= done:
                ordered.append(CompiledStep(
                    node_id=node.node_id, type=node.type, skill_id=skill_id,
                    resource=resource, client_job_id=client_job_id,
                    inputs=tuple((item.kind, item.ref) for item in node.inputs),
                    depends_on=node.depends_on, token_budget=budget))
                done.add(node.node_id)
                break
        else:  # pragma: no cover - schema validator already rejects cycles
            raise ValueError('Workflow dependency cycle')

    payload = {'envelope_hash': plan.envelope_hash, 'plan_id': plan.plan_id,
               'revision': plan.revision,
               'steps': [step.model_dump() for step in ordered]}
    digest = sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False,
                               allow_nan=False).encode('utf-8')).hexdigest()
    return CompiledWorkflow(compile_hash=digest, envelope_hash=plan.envelope_hash,
                            plan_id=plan.plan_id, revision=plan.revision,
                            steps=tuple(ordered))


def from_execution_plan(legacy, *, envelope) -> WorkflowPlan:
    """Compatibility adapter: old ExecutionPlan becomes a declarative workflow."""
    from .execution_plan import ExecutionPlan

    legacy = ExecutionPlan.model_validate(
        legacy.model_dump() if isinstance(legacy, ExecutionPlan) else legacy)
    envelope = TurnEnvelope.model_validate(envelope.model_dump())
    nodes: list[WorkflowNode] = []
    for step in legacy.steps:
        nodes.append(WorkflowNode(
            node_id=step.step_id, type='run_skill',
            inputs=tuple(NodeInput(kind='attachment', ref=ref)
                         for ref in step.inputs),
            depends_on=tuple(step.dependencies),
            config={'skill_id': step.skill_id},
        ))
    produced = [step.step_id for step in legacy.steps]
    nodes.append(WorkflowNode(
        node_id='validate', type='validate_artifact',
        inputs=tuple(NodeInput(kind='node_output', ref=ref)
                     for ref in produced),
        depends_on=tuple(produced), config={}))
    nodes.append(WorkflowNode(
        node_id='deliver', type='deliver',
        inputs=(NodeInput(kind='node_output', ref='validate'),),
        depends_on=('validate',), config={}))
    return WorkflowPlan(plan_id=legacy.identity.task_id, revision=legacy.revision,
                        envelope_hash=envelope_hash(envelope),
                        revision_reason='legacy-execution-plan-compat',
                        nodes=tuple(nodes))
