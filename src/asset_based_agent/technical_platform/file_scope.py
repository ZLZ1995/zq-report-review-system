"""Freeze explicit local file roles. No inference, file reads, or grants."""
from dataclasses import dataclass


@dataclass(frozen=True)
class FileScope:
    owner: str
    project_id: str
    session_id: str
    revision: int
    targets: tuple[tuple[str, str], ...]
    references: tuple[tuple[str, str], ...]
    excluded: tuple[tuple[str, str], ...]

    def to_snapshot(self):
        result = {'schema_version': 1, 'owner': self.owner, 'project_id': self.project_id,
                  'session_id': self.session_id, 'revision': self.revision}
        for role in ('targets', 'references', 'excluded'):
            result[role] = [{'id': identity, 'sha256': version}
                            for identity, version in getattr(self, role)]
        return result


def freeze_scope(store, session_id, *, targets, references=(), excluded=(), revision):
    if type(revision) is not int or revision < 1:
        raise ValueError('文件范围修订号无效')
    session = store.session(session_id)
    available = {item['id']: item for item in store.files(session['project'])}
    seen, groups = set(), []
    for items in (targets, references, excluded):
        group = []
        for item in items:
            if not isinstance(item, dict) or available.get(item.get('id')) != item:
                raise PermissionError('文件不属于当前项目或文件记录已变化')
            if item['id'] in seen:
                raise ValueError('文件范围重复或目标、参考、排除角色冲突')
            seen.add(item['id'])
            group.append((item['id'], item['sha256']))
        groups.append(tuple(group))
    if not groups[0]:
        raise ValueError('本轮目标文件不能为空，不会自动选择历史文件')
    return FileScope(store.owner, session['project'], session_id, revision, *groups)
