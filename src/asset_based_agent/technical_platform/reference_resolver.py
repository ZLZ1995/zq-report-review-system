"""Resolve structured references against a trusted, explicitly bounded local view.

Language understanding supplies references, never filesystem paths. Ambiguous
names return candidates for clarification rather than selecting the newest row.
"""
import re
import unicodedata
from dataclasses import dataclass


@dataclass(frozen=True)
class FileResolution:
    status: str
    file_id: str | None
    candidate_ids: tuple[str, ...]


def resolve_file(store, session_id, reference, *, candidate_ids):
    if (not isinstance(reference, dict) or not reference or
            set(reference) - {'id', 'name', 'sha256'} or
            not ({'id', 'name'} & set(reference)) or
            any(not isinstance(v, str) or not v.strip() or len(v) > 1024
                for v in reference.values())):
        raise ValueError('文件引用必须是明确的ID或名称，可附版本，不接受路径')
    if 'sha256' in reference and not re.fullmatch('[0-9a-f]{64}', reference['sha256']):
        raise ValueError('文件版本无效')
    session = store.session(session_id)
    available = {item['id']: item for item in store.files(session['project'])}
    if (not isinstance(candidate_ids, (list, tuple)) or
            any(not isinstance(i, str) for i in candidate_ids) or
            len(set(candidate_ids)) != len(candidate_ids)):
        raise ValueError('文件候选范围无效')
    if any(i not in available for i in candidate_ids):
        raise PermissionError('文件候选不属于当前项目')
    matches = []
    for identity in candidate_ids:
        item = available[identity]
        if any((unicodedata.normalize('NFC', item[k]).casefold() !=
                unicodedata.normalize('NFC', value).casefold()) if k == 'name'
               else item[k] != value for k, value in reference.items()):
            continue
        matches.append(identity)
    if len(matches) == 1:
        return FileResolution('resolved', matches[0], tuple(matches))
    return FileResolution('ambiguous' if matches else 'missing', None, tuple(matches))
