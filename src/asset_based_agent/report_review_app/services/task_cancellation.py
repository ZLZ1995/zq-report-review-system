"""Interrupt waiting on read/network work without terminating Python threads."""
from threading import Event, Thread


class TaskCancelled(Exception):
    pass


def cancellable_call(function, cancel=None):
    if cancel is None:
        return function()
    if cancel.is_set():
        raise TaskCancelled('任务已取消')
    done = Event()
    results, errors = [], []
    def invoke():
        try:
            results.append(function())
        except BaseException as exc:  # noqa: BLE001 - transfer worker exception to owner
            errors.append(exc)
        finally:
            done.set()
    Thread(target=invoke, daemon=True).start()
    while not done.wait(0.05):
        if cancel.is_set():
            raise TaskCancelled('已停止等待；已提交的服务端调用可能仍在结束处理中')
    if cancel.is_set():
        raise TaskCancelled('任务已取消，不接收迟到结果')
    if errors:
        raise errors[0]
    return results[0]
