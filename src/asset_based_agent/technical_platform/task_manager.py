"""In-process worker ownership; cancellation never implies remote rollback.

This registry does not authorize execution or replace durable Harness claims.
Workers stay registered until their thread has actually terminated.
"""

from dataclasses import dataclass
from threading import Event, RLock
from typing import Protocol


class ManagedWorker(Protocol):
    cancel: Event

    def isRunning(self) -> bool: ...


@dataclass(frozen=True)
class TaskBinding:
    owner: str
    project_id: str
    session_id: str
    task_id: str

    def __post_init__(self) -> None:
        if any(not isinstance(value, str) or not value.strip() for value in (
            self.owner, self.project_id, self.session_id, self.task_id,
        )):
            raise ValueError('Task identity must be nonempty')


class TaskManager:
    def __init__(self) -> None:
        self._workers: dict[TaskBinding, ManagedWorker] = {}
        self._lock = RLock()

    def register(self, binding: TaskBinding, worker: ManagedWorker) -> None:
        with self._lock:
            for existing, registered in self._workers.items():
                if registered is worker or (
                    existing.owner == binding.owner
                    and existing.project_id == binding.project_id
                    and (existing.task_id == binding.task_id
                         or existing.session_id == binding.session_id)
                ):
                    raise ValueError('Task, session or worker already active')
            self._workers[binding] = worker

    def active(self) -> tuple[TaskBinding, ...]:
        with self._lock:
            return tuple(self._workers)

    def owns(self, binding: TaskBinding, worker: ManagedWorker) -> bool:
        with self._lock:
            return self._workers.get(binding) is worker

    def for_session(self, owner: str, project_id: str | None, session_id: str | None) -> ManagedWorker | None:
        with self._lock:
            return next((worker for scope, worker in self._workers.items()
                         if (scope.owner, scope.project_id, scope.session_id)
                         == (owner, project_id, session_id)), None)

    def cancel(self, binding: TaskBinding) -> bool:
        with self._lock:
            worker = self._workers.get(binding)
            if worker is None:
                return False
            worker.cancel.set()
            return True

    def cancel_all(self) -> int:
        with self._lock:
            for worker in self._workers.values():
                worker.cancel.set()
            return len(self._workers)

    def finish(self, binding: TaskBinding, worker: ManagedWorker) -> bool:
        with self._lock:
            if self._workers.get(binding) is not worker:
                return False
            if worker.isRunning():
                raise ValueError('Cannot release a running worker')
            del self._workers[binding]
            return True
