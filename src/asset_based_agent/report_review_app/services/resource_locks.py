"""Client resource leases, including cross-process Office/output exclusion."""

import hashlib
import importlib
import os
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from threading import Condition, Event
from typing import Any, BinaryIO, cast

from .task_cancellation import TaskCancelled


class ResourceLocks:
    def __init__(self, *, process_lock_root: Path | None = None) -> None:
        self._condition = Condition()
        self._used: dict[str, int] = {}
        self._updating = False
        self._process_lock_root = process_lock_root

    @contextmanager
    def update_barrier(self) -> Iterator[None]:
        with self._condition:
            if self._used or self._updating:
                raise ValueError('Update requires idle execution resources')
            self._updating = True
        try:
            yield
        finally:
            with self._condition:
                self._updating = False
                self._condition.notify_all()

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
        process_lease: _ProcessLease | None = None
        while process_lease is None:
            with self._condition:
                if self._updating:
                    raise ValueError('Client update blocks new execution resources')
                if cancel is not None and cancel.is_set():
                    raise TaskCancelled('等待执行资源时已取消，未启动下一步')
                if all(self._used.get(name, 0) < limit for name, limit in limits.items()):
                    for name in names:
                        self._used[name] = self._used.get(name, 0) + 1
                else:
                    self._condition.wait(.05)
                    continue
            candidate = _ProcessLease(self._process_lock_root, limits)
            try:
                acquired = candidate.try_acquire()
            except Exception:
                with self._condition:
                    self._release_local(names)
                    self._condition.notify_all()
                raise
            if acquired:
                process_lease = candidate
                break
            with self._condition:
                self._release_local(names)
                self._condition.wait(.05)
        try:
            yield
        finally:
            try:
                process_lease.release()
            finally:
                with self._condition:
                    self._release_local(names)
                    self._condition.notify_all()

    def _release_local(self, names: tuple[str, ...]) -> None:
        for name in names:
            self._used[name] -= 1
            if not self._used[name]:
                del self._used[name]


class _ProcessLease:
    def __init__(self, root: Path | None, limits: dict[str, int]) -> None:
        self._root = root
        self._limits = limits
        self._files: list[BinaryIO] = []

    def try_acquire(self) -> bool:
        if self._root is None:
            return True
        self._root.mkdir(parents=True, exist_ok=True)
        for name in sorted(self._limits):
            if not self._acquire_one(name, self._limits[name]):
                self.release()
                return False
        return True

    def _acquire_one(self, name: str, capacity: int) -> bool:
        assert self._root is not None
        identity = hashlib.sha256(name.encode('utf-8')).hexdigest()
        for slot in range(capacity):
            path = self._root / f'{identity}.{slot}.lock'
            handle = path.open('a+b', buffering=0)
            if _try_file_lock(handle):
                self._files.append(handle)
                return True
            handle.close()
        return False

    def release(self) -> None:
        while self._files:
            handle = self._files.pop()
            try:
                _unlock_file(handle)
            finally:
                handle.close()


def _try_file_lock(handle: BinaryIO) -> bool:
    handle.seek(0, os.SEEK_END)
    if handle.tell() == 0:
        handle.write(b'\0')
    handle.seek(0)
    try:
        if os.name == 'nt':
            import msvcrt

            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            fcntl = cast(Any, importlib.import_module('fcntl'))

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return False
    return True


def _unlock_file(handle: BinaryIO) -> None:
    handle.seek(0)
    if os.name == 'nt':
        import msvcrt

        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        fcntl = cast(Any, importlib.import_module('fcntl'))

        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


CLIENT_RESOURCES = ResourceLocks(
    process_lock_root=Path(tempfile.gettempdir()) / 'zq-workspace-resource-locks'
)
