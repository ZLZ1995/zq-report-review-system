"""确定性指代解析（任务书 S10 验收语料）。

只做可测试的规则匹配：无法确定的指代保持未解析（空结果），绝不猜测。
"""
import re

_FILE_PRONOUNS = ('刚才那个文件', '那个文件', '该文件', '这份文件', '它')
_NEW_UPLOAD = re.compile(r'新上传的([两二三四五]|\d+)个文件')
_PERIOD_OVERRIDE = re.compile(r'期间改为\s*([^，。,]+)')
_NUMERALS = {'两': 2, '二': 2, '三': 3, '四': 4, '五': 5}


def resolve_references(text, *, bindings, entries):
    text = str(text or '').strip()
    outcome = {'continuation': False, 'file_ids': [], 'action_hints': [],
               'overrides': {}, 'used_last_facts': False}
    explicit = [b for b in bindings
                if str(b.get('binding_kind', '')).startswith('explicit')]
    uploads = [b for b in bindings if b.get('binding_kind') == 'explicit_upload']
    if text.startswith('继续'):
        outcome['continuation'] = True
    new_upload = _NEW_UPLOAD.search(text)
    if new_upload and uploads:
        token = new_upload.group(1)
        count = _NUMERALS.get(token) or int(token)
        outcome['file_ids'] = [b['file_id'] for b in uploads[-count:]]
    elif any(pronoun in text for pronoun in _FILE_PRONOUNS) and explicit:
        outcome['file_ids'] = [explicit[-1]['file_id']]
    if '审核' in text:
        outcome['action_hints'].append('review')
    if '上传' in text and new_upload is None:
        outcome['action_hints'].append('external_upload')
    if '上次的口径' in text:
        outcome['used_last_facts'] = True
    period = _PERIOD_OVERRIDE.search(text)
    if period:
        outcome['overrides']['期间'] = period.group(1).replace(' ', '')
    return outcome
