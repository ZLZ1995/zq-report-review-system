"""Versioned dependency plans; validation does not issue execution permissions."""
from typing import Annotated

from pydantic import Field, model_validator

from .execution_contracts import (
    Contract,
    IdentityText,
    PlanStep,
    Positive,
    TaskIdentity,
)
from .skills import BROWSER, BUILTINS
from .tool_contracts import tool_contract

Hash = Annotated[str, Field(pattern=r'^[0-9a-f]{64}$')]


class ExecutionStep(PlanStep):
    tool_version: Positive
    skill_id: IdentityText
    skill_version: IdentityText
    rules_sha256: Hash
    inputs: list[IdentityText] = Field(max_length=100)
    output_ref: IdentityText
    goal: str = Field(default='', max_length=1000)
    constraints: list[str] = Field(default_factory=list, max_length=20)
    target_inputs: list[IdentityText] = Field(default_factory=list, max_length=100)
    reference_inputs: list[IdentityText] = Field(default_factory=list, max_length=100)

    @model_validator(mode='after')
    def trusted_adapter(self):
        tool = tool_contract(self.tool)
        versions = {s.id: s.version for s in (*BUILTINS, BROWSER)}
        if (tool.resource != 'browser' and not self.inputs) or (
                tool.resource == 'browser' and (self.inputs or self.target_inputs or self.reference_inputs)):
            raise ValueError('Tool input scope mismatch')
        if (tool.version != self.tool_version or tool.skill_id != self.skill_id or
                versions.get(self.skill_id) != self.skill_version or
                not set(tool.acceptance_gates) <= set(self.acceptance_gates) or
                len(set(self.inputs)) != len(self.inputs)):
            raise ValueError('Step tool, version, inputs or validation gates mismatch')
        roles = self.target_inputs + self.reference_inputs
        if roles and (not self.target_inputs or len(roles) != len(set(roles)) or set(roles) != set(self.inputs)):
            raise ValueError('Step file roles do not match inputs')
        if any(not item.strip() or len(item) > 1000 for item in self.constraints):
            raise ValueError('Invalid step constraint')
        return self


class ExecutionPlan(Contract):
    identity: TaskIdentity
    revision: Positive
    input_versions: dict[IdentityText, Hash] = Field(max_length=100)
    steps: list[ExecutionStep] = Field(min_length=1, max_length=32)

    @model_validator(mode='after')
    def scoped_dag(self):
        by_id = {step.step_id: step for step in self.steps}
        producers = {step.output_ref: step.step_id for step in self.steps}
        if (len(by_id) != len(self.steps) or len(producers) != len(self.steps) or
                set(producers) & set(self.input_versions)):
            raise ValueError('Duplicate step or output identity')
        for step in self.steps:
            if step.identity != self.identity or not set(step.dependencies) <= set(by_id):
                raise ValueError('Cross-task step or unknown dependency')
        completed: set[str] = set()
        while len(completed) != len(self.steps):
            ready = self.ready_steps(completed)
            if not ready:
                raise ValueError('Dependency cycle')
            completed.update(ready)
        for step in self.steps:
            ancestors, todo = set(), list(step.dependencies)
            while todo:
                dependency = todo.pop()
                if dependency not in ancestors:
                    ancestors.add(dependency)
                    todo.extend(by_id[dependency].dependencies)
            for reference in step.inputs:
                if reference not in self.input_versions and producers.get(reference) not in ancestors:
                    raise ValueError('Input outside plan or not produced by a dependency')
        return self

    def ready_steps(self, completed: set[str]):
        known = {s.step_id for s in self.steps}
        if not completed <= known:
            raise ValueError('Unknown completed step')
        return [s.step_id for s in self.steps
                if s.step_id not in completed and set(s.dependencies) <= completed]
