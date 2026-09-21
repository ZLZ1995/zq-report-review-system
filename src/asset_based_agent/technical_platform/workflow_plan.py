"""Declarative WorkflowPlan: the model proposes, the compiler disposes.

Nodes are data only. There is no code, no path and no permission field a
model could smuggle through: unknown node types, duplicate ids, dependency
cycles, dangling references and orphan deliveries are rejected at schema
time; local compilation adds scope, tool and budget checks.
"""
from __future__ import annotations

from typing import Literal

from pydantic import Field, field_validator, model_validator

from ..agent_contracts import Identifier, Record

NodeType = Literal['understand', 'classify_materials', 'extract_evidence',
                   'model_call', 'run_skill', 'browser_action',
                   'validate_artifact', 'verify_business_result',
                   'ask_user', 'deliver']


class NodeInput(Record):
    kind: Literal['attachment', 'node_output', 'literal', 'envelope_field']
    ref: str = Field(min_length=1, max_length=512)


class WorkflowNode(Record):
    node_id: Identifier
    type: NodeType
    inputs: tuple[NodeInput, ...] = ()
    depends_on: tuple[Identifier, ...] = ()
    config: dict[str, object] = Field(default_factory=dict, max_length=20)

    @field_validator('inputs', 'depends_on', mode='before')
    @classmethod
    def coerce_tuple(cls, value):
        return tuple(value) if isinstance(value, list) else value


class WorkflowPlan(Record):
    schema_version: Literal[1] = 1
    plan_id: Identifier
    revision: int = Field(ge=1)
    envelope_hash: str = Field(pattern=r'^[0-9a-f]{64}$')
    revision_reason: str = Field(min_length=1, max_length=500)
    nodes: tuple[WorkflowNode, ...] = Field(min_length=1, max_length=64)

    @field_validator('nodes', mode='before')
    @classmethod
    def coerce_nodes(cls, value):
        return tuple(value) if isinstance(value, list) else value

    @field_validator('schema_version', mode='before')
    @classmethod
    def integer_version(cls, value):
        if type(value) is not int:
            raise ValueError('Invalid schema version')
        return value

    @model_validator(mode='after')
    def coherent_dag(self):
        by_id = {node.node_id: node for node in self.nodes}
        if len(by_id) != len(self.nodes):
            raise ValueError('Duplicate workflow node')
        for node in self.nodes:
            if node.node_id in node.depends_on:
                raise ValueError('Node depends on itself')
            if not set(node.depends_on) <= set(by_id):
                raise ValueError('Unknown node dependency')
            for item in node.inputs:
                if item.kind == 'node_output' and item.ref not in by_id:
                    raise ValueError('Input references an unknown node')
        completed: set[str] = set()
        while len(completed) != len(by_id):
            ready = {node.node_id for node in self.nodes
                     if node.node_id not in completed
                     and set(node.depends_on) <= completed}
            if not ready:
                raise ValueError('Workflow dependency cycle')
            completed.update(ready)
        deliverers = [node for node in self.nodes if node.type == 'deliver']
        if not deliverers:
            raise ValueError('Workflow requires a deliver sink')
        for node in deliverers:
            if not node.inputs or not node.depends_on:
                raise ValueError('Orphan deliver node')
            for item in node.inputs:
                if item.kind == 'node_output' and item.ref not in completed:
                    raise ValueError('Deliver input is unreachable')
        return self


def revise_plan(plan: WorkflowPlan, *, reason: str) -> WorkflowPlan:
    """A revision keeps identity and records why it differs."""
    plan = WorkflowPlan.model_validate(plan.model_dump())
    if not reason or not reason.strip():
        raise ValueError('修订必须说明差异原因')
    return plan.model_copy(update={'revision': plan.revision + 1,
                                   'revision_reason': reason})
