"""Deterministic local directories; model step names never become path segments."""
import re
from hashlib import sha256
from pathlib import Path


def generation_work_directory(root, run_id, step_id=None, *, create=False):
    root = Path(root).resolve()
    if not isinstance(run_id, str) or re.fullmatch(r'[A-Za-z0-9_-]{1,128}', run_id) is None:
        raise ValueError('Invalid generation task identity')
    parents = [root / 'runs']
    work = parents[0] / run_id
    if step_id is not None:
        if not isinstance(step_id, str) or not step_id or len(step_id) > 128:
            raise ValueError('Invalid generation step identity')
        parents.extend([work, work / 'steps'])
        work = parents[-1] / sha256(step_id.encode('utf-8')).hexdigest()
    for path in [*parents, work]:
        if path.resolve() != path:
            raise PermissionError('Generation directory has been redirected')
        if create:
            path.mkdir(exist_ok=path != work)
            if path.resolve() != path:
                raise PermissionError('Generation directory has been redirected')
    return work
