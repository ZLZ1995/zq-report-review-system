"""Wait for the owning client to exit before the independent updater writes."""

from __future__ import annotations

import ctypes
import os
import time
from collections.abc import Callable


def process_running(process_id: int) -> bool:
    if os.name == 'nt':
        kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)  # type: ignore[attr-defined]
        handle = kernel32.OpenProcess(0x00100000, False, process_id)
        if not handle:
            return ctypes.get_last_error() == 5  # type: ignore[attr-defined]
        try:
            return kernel32.WaitForSingleObject(handle, 0) == 0x00000102
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(process_id, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def wait_for_process_exit(
        process_id: int, *, timeout: float = 120.0,
        is_running: Callable[[int], bool] = process_running,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
) -> None:
    if type(process_id) is not int or process_id <= 0:
        raise ValueError('Valid owner process ID required')
    deadline = clock() + timeout
    while is_running(process_id):
        if clock() >= deadline:
            raise TimeoutError('Client did not exit before update timeout')
        sleep(0.25)
