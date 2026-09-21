"""Workflow runtime: DAG execution with locks, cancel, retry, resume.

Retryable faults (timeouts, connection errors) get bounded attempts with
backoff. Business contract faults fail the run immediately. Anything else is
treated as a crash: locks are released and the exception propagates without a
terminal event, so a later resume re-runs only uncommitted nodes.
"""
from __future__ import annotations

import json
import threading
from datetime import datetime
from datetime import timezone as tz
from hashlib import sha256

from ..agent_contracts import Identifier, Record
from .workflow_compiler import CompiledWorkflow
from .workflow_journal import WorkflowJournal
from .workflow_scheduler import ResourcePool, ready_nodes

RETRYABLE = (TimeoutError, ConnectionError)
NON_RETRYABLE = (ValueError, PermissionError, KeyError, TypeError)
MAX_IDLE_CYCLES = 100


class RunResult(Record):
    run_id: Identifier
    state: str
    committed: tuple[Identifier, ...] = ()


def _now() -> str:
    return datetime.now(tz.utc).isoformat()


def node_cache_key(compiled: CompiledWorkflow, step, *, permission_snapshot: str,
                   dependency_results=()) -> str:
    """Cache key binds plan version, node, tool, inputs and permission snapshot."""
    payload = {
        'plan_id': compiled.plan_id, 'revision': compiled.revision,
        'node_id': step.node_id, 'type': step.type, 'skill_id': step.skill_id,
        'inputs': [list(item) for item in step.inputs],
        'token_budget': step.token_budget,
        'permission_snapshot': permission_snapshot,
        'dependency_results': [str(item) for item in dependency_results],
    }
    return sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False,
                             allow_nan=False).encode('utf-8')).hexdigest()


class WorkflowRuntime:
    def __init__(self, journal: WorkflowJournal, executors: dict, *,
                 sleeper=None, max_attempts=1):
        if type(max_attempts) is not int or max_attempts < 1:
            raise ValueError('重试上限必须是正整数')
        self.journal = journal
        self.executors = dict(executors)
        self._sleeper = sleeper
        self.max_attempts = max_attempts
        self._pool = ResourcePool()

    def run(self, compiled, *, run_id, cancel=None, sleeper=None) -> RunResult:
        compiled = CompiledWorkflow.model_validate(
            compiled.model_dump() if isinstance(compiled, CompiledWorkflow) else compiled)
        cancel = cancel or threading.Event()
        sleep = sleeper or self._sleeper or (lambda _seconds: None)
        if not self.journal.events(run_id):
            self.journal.append(run_id=run_id, node_id=None, type='run_created',
                                at=_now(), payload={'compile_hash': compiled.compile_hash})
        committed = self.journal.committed_nodes(run_id)
        results: dict[str, object] = {}
        idle = 0
        try:
            while True:
                if cancel.is_set():
                    self.journal.append(run_id=run_id, node_id=None,
                                        type='run_terminal', at=_now(),
                                        payload={'state': 'cancelled'})
                    return RunResult(run_id=run_id, state='cancelled',
                                     committed=tuple(sorted(committed)))
                pending = [step for step in ready_nodes(compiled.steps, committed)
                           if step.node_id not in results]
                if not pending:
                    remaining = [step for step in compiled.steps
                                 if step.node_id not in committed]
                    if not remaining:
                        self.journal.append(run_id=run_id, node_id=None,
                                            type='run_terminal', at=_now(),
                                            payload={'state': 'succeeded'})
                        return RunResult(run_id=run_id, state='succeeded',
                                         committed=tuple(sorted(committed)))
                    idle += 1
                    if idle > MAX_IDLE_CYCLES:
                        raise RuntimeError('工作流资源等待超时，疑似死锁')
                    sleep(0.1)
                    continue
                idle = 0
                for step in pending:
                    if step.resource and not self._pool.try_acquire(step.resource, run_id):
                        self.journal.append(run_id=run_id, node_id=step.node_id,
                                            type='node_waiting_resource', at=_now(),
                                            payload={'resource': step.resource})
                        sleep(0.1)
                        continue
                    try:
                        self._execute(compiled, step, run_id, results, sleep)
                    except _NodeFailed:
                        self.journal.append(run_id=run_id, node_id=None,
                                            type='run_terminal', at=_now(),
                                            payload={'state': 'failed'})
                        return RunResult(run_id=run_id, state='failed',
                                         committed=tuple(sorted(committed)))
                    finally:
                        if step.resource:
                            self._pool.release(step.resource, run_id)
                    committed.add(step.node_id)
        finally:
            self._pool.release_all(run_id)

    def _execute(self, compiled, step, run_id, results, sleep):
        executor = self.executors.get(step.type)
        if executor is None:
            raise ValueError('没有登记该节点类型的执行器')
        inputs = {kind: ref for kind, ref in step.inputs}
        resolved = {ref: results[ref] for kind, ref in step.inputs
                    if kind == 'node_output' and ref in results}
        self.journal.append(run_id=run_id, node_id=step.node_id,
                            type='node_claimed', at=_now(), payload={})
        self.journal.append(run_id=run_id, node_id=step.node_id,
                            type='node_started', at=_now(), payload={})
        attempts = self.max_attempts
        while True:
            try:
                output = executor(step, {'inputs': inputs, 'resolved': resolved})
                break
            except NON_RETRYABLE as exc:
                self.journal.append(run_id=run_id, node_id=step.node_id,
                                    type='node_failed', at=_now(),
                                    payload={'reason': type(exc).__name__})
                raise _NodeFailed() from exc
            except RETRYABLE as exc:
                attempts -= 1
                if attempts <= 0:
                    self.journal.append(run_id=run_id, node_id=step.node_id,
                                        type='node_failed', at=_now(),
                                        payload={'reason': type(exc).__name__})
                    raise _NodeFailed() from exc
                self.journal.append(run_id=run_id, node_id=step.node_id,
                                    type='node_retrying', at=_now(),
                                    payload={'reason': type(exc).__name__})
                sleep(0.1)
            # 其他异常视为进程级崩溃：不写终态，直接上抛，恢复时重跑未提交节点
        results[step.node_id] = output
        self.journal.append(run_id=run_id, node_id=step.node_id,
                            type='node_result_committed', at=_now(),
                            payload={'cache_key': node_cache_key(
                                compiled, step,
                                permission_snapshot='runtime')})


class _NodeFailed(Exception):
    pass
