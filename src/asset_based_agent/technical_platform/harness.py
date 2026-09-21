"""Sequential DAG scheduler with consent checks and durable step boundaries.

This scheduler does not reclaim interrupted work. A remote reconciliation flow
must establish an outcome before any such work can safely be resumed.
"""
import json

from ..report_review_app.services.task_cancellation import TaskCancelled
from .event_store import ExecutionStore
from .execution_plan import ExecutionPlan
from .permissions import PermissionService
from .step_results import StepResults
from .tool_dispatcher import ToolOutcome


def execute_plan(store, run_id, plan, dispatcher, cancel):
    # Duplicate callers must not alter the winning executor's run.
    store.claim_run(run_id)
    return _execute_claimed_plan(store, run_id, plan, dispatcher, cancel)


def _execute_claimed_plan(store, run_id, plan, dispatcher, cancel, *, raise_errors=False):
    """Internal bridge for the existing task entry after its atomic run claim."""
    if store.run(run_id)['state'] != 'running':
        raise ValueError('Task has not been claimed')
    events, permissions = ExecutionStore(store), PermissionService(store)
    active = None
    try:
        plan = ExecutionPlan.model_validate(plan.model_dump())
        if plan.identity.task_id != run_id:
            raise PermissionError('Plan task mismatch')
        permissions.verify(run_id)
        dispatcher.validate(plan)
        events.register(plan)
        completed = {}
        while len(completed) < len(plan.steps):
            if cancel.is_set():
                store.transition(run_id, 'cancelled', 'harness: stopped before next step')
                return 'cancelled'
            permissions.verify(run_id)
            ready = plan.ready_steps(set(completed))
            if not ready:
                raise ValueError('No executable dependency frontier')
            step = next(step for step in plan.steps if step.step_id == ready[0])
            token = events.claim(run_id, step.step_id)
            active = (step, token)
            dependencies = {key: completed[key] for key in step.dependencies}
            outcome = dispatcher.execute(step, dependencies, cancel)
            if cancel.is_set() and outcome.status == 'succeeded':
                outcome = ToolOutcome(step_id=step.step_id, status='cancelled')
            events.finish_step(run_id, step.step_id, token, outcome)
            active = None
            if outcome.status == 'unknown':
                store.interrupt_active_runs([run_id])
                return 'reconciliation_required'
            if outcome.status == 'waiting_user':
                if outcome.result_ref is not None:
                    store.save_result(run_id, StepResults(store).read(run_id, step.step_id, outcome.result_ref))
                store.transition(run_id, 'waiting_user', 'harness: step waits for user clarification')
                return 'waiting_user'
            if outcome.status != 'succeeded':
                if len(plan.steps) == 1 and outcome.result_ref is not None:
                    store.save_result(run_id, StepResults(store).read(run_id, step.step_id, outcome.result_ref))
                store.transition(run_id, outcome.status, 'harness: step did not succeed')
                return outcome.status
            completed[step.step_id] = outcome
        permissions.verify(run_id)
        store.transition(run_id, 'validating', 'harness: all step gates passed')
        result = {'kind': 'plan', 'steps': {key: value.model_dump() for key, value in completed.items()}}
        if len(completed) == 1 and json.loads(store.run(run_id)['snapshot']).get('mode') != 'compound':
            step_id, outcome = next(iter(completed.items()))
            if outcome.result_ref is not None:
                result = StepResults(store).read(run_id, step_id, outcome.result_ref)
        store.save_result(run_id, result)
        store.transition(run_id, 'succeeded', 'harness: plan completed')
        return 'succeeded'
    except Exception as exc:
        # Do not put exception text (which may include provider secrets) in events.
        status = ('cancelled' if isinstance(exc, TaskCancelled) else
                  'failed' if isinstance(exc, (ValueError, PermissionError)) else 'unknown')
        if active is not None:
            step, token = active
            events.finish_step(run_id, step.step_id, token, ToolOutcome(step_id=step.step_id, status=status))
        if status == 'unknown':
            store.interrupt_active_runs([run_id])
            if raise_errors:
                raise
            return 'reconciliation_required'
        if store.run(run_id)['state'] in {'running', 'validating'}:
            store.transition(run_id, status, 'harness: ' + type(exc).__name__)
        if raise_errors and status != 'cancelled':
            raise
        return status
