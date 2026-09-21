import pytest

from asset_based_agent.technical_platform.updates.process_wait import (
    wait_for_process_exit,
)


def test_wait_for_process_exit_returns_after_owner_stops():
    states = iter((True, True, False))
    sleeps = []
    clock_values = iter((0.0, 0.1, 0.2, 0.3))
    wait_for_process_exit(
        123, timeout=1.0, is_running=lambda _pid: next(states),
        clock=lambda: next(clock_values), sleep=sleeps.append,
    )
    assert sleeps == [0.25, 0.25]


def test_wait_for_process_exit_times_out_without_installing():
    clock_values = iter((0.0, 2.0))
    with pytest.raises(TimeoutError):
        wait_for_process_exit(
            123, timeout=1.0, is_running=lambda _pid: True,
            clock=lambda: next(clock_values), sleep=lambda _seconds: None,
        )


@pytest.mark.parametrize('pid', [0, -1])
def test_wait_for_process_exit_rejects_invalid_pid(pid):
    with pytest.raises(ValueError):
        wait_for_process_exit(pid, timeout=1.0)
