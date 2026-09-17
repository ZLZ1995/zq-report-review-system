"""Process-local resource leases. Server limits still require server enforcement."""

from collections.abc import Iterator
from contextlib import contextmanager
from threading import Condition, Event

from .task_cancellation import TaskCancelled


class ResourceLocks:
    def __init__(self) -> None:
        self._condition = Condition()
        self._used: dict[str, int] = {}

    def busy(self) -> bool:
        with self._condition:
            return bool(self._used)

    @staticmethod
    def _capacity(name: str) -> int:
        if name == 'model':
            return 2
        if name == 'office' or (name.startswith('output:') and len(name) > 7):
            return 1
        raise ValueError('Unknown execution resource')

    @contextmanager
    def lease(self, names: tuple[str, ...], cancel: Event | None = None) -> Iterator[None]:
        if not names or len(set(names)) != len(names):
            raise ValueError('Resource request must be nonempty and unique')
        limits = {name: self._capacity(name) for name in names}
        with self._condition:
            while True:
                if cancel is not None and cancel.is_set():
                    raise TaskCancelled('等待执行资源时已取消，未启动下一步')
                if all(self._used.get(name, 0) < limit for name, limit in limits.items()):
                    for name in names:
                        self._used[name] = self._used.get(name, 0) + 1
                    break
                self._condition.wait(.05)
        try:
            yield
        finally:
            with self._condition:
                for name in names:
                    self._used[name] -= 1
                    if not self._used[name]:
                        del self._used[name]
                self._condition.notify_all()


CLIENT_RESOURCES = ResourceLocks()
