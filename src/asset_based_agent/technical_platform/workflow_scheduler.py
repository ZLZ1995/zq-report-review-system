"""Resource scheduling: named locks for Office, workbooks, output dirs,
browser pages and model channels. One writer per resource, ever.
"""
from __future__ import annotations


class ResourcePool:
    def __init__(self):
        self._owners: dict[str, str] = {}

    def try_acquire(self, name: str, owner: str) -> bool:
        if not name or not owner:
            raise ValueError('资源与占用方不能为空')
        holder = self._owners.get(name)
        if holder is None or holder == owner:
            self._owners[name] = owner
            return True
        return False

    def release(self, name: str, owner: str):
        holder = self._owners.get(name)
        if holder is None:
            return
        if holder != owner:
            raise PermissionError('资源锁不属于该占用方')
        del self._owners[name]

    def release_all(self, owner: str):
        for name in [name for name, holder in self._owners.items()
                     if holder == owner]:
            del self._owners[name]

    def holder(self, name: str) -> str | None:
        return self._owners.get(name)


def ready_nodes(steps, completed: set[str]):
    """DAG ready queue: steps whose dependencies are all committed."""
    return [step for step in steps
            if step.node_id not in completed and set(step.depends_on) <= completed]
