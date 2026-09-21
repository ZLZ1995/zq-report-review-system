"""Dispatch only application-registered adapters; LLM JSON is never executable."""
from typing import Literal

from pydantic import Field

from .execution_contracts import Contract, IdentityText
from .tool_contracts import tool_contract


class InvalidToolOutcome(ValueError):
    """An adapter returned a result that cannot pass the execution contract."""


class ToolOutcome(Contract):
    step_id: IdentityText
    status: Literal['succeeded', 'failed', 'cancelled', 'unknown', 'waiting_user']
    passed_gates: list[IdentityText] = Field(default_factory=list, max_length=50)
    result_ref: IdentityText | None = None


def validate_outcome(step, outcome):
    if not isinstance(outcome, ToolOutcome):
        raise InvalidToolOutcome('Adapter did not return a typed outcome')
    outcome = ToolOutcome.model_validate(outcome.model_dump())
    if outcome.step_id != step.step_id:
        raise ValueError('Adapter returned a result for another step')
    if outcome.status == 'succeeded' and set(outcome.passed_gates) != set(step.acceptance_gates):
        raise ValueError('Adapter did not satisfy all acceptance gates')
    return outcome


class ToolDispatcher:
    def __init__(self, adapters):
        self._adapters = dict(adapters)
        for identity, adapter in self._adapters.items():
            tool_contract(identity)
            if not callable(adapter):
                raise TypeError('Adapter must be registered application code')

    def validate(self, plan):
        if any(step.tool not in self._adapters for step in plan.steps):
            raise ValueError('Plan contains an unavailable adapter')

    def execute(self, step, dependencies, cancel):
        if step.tool not in self._adapters:
            raise ValueError('Adapter is not installed')
        return validate_outcome(step, self._adapters[step.tool](step, dependencies, cancel))
