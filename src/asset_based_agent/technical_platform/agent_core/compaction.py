"""Compaction：确定性关键项提取与 10.4 守恒校验。

任一关键项（用户目标/文件范围/排除项/权限限制/已确认事实/未决问题/
Artifact 引用/当前进度）在摘要中丢失或被改写，压缩即无效，不得保存、
不得替换旧上下文。
"""
import json
from hashlib import sha256

KEY_ITEMS = ('user_goal', 'file_scope', 'exclusions', 'permission_limits',
             'confirmed_facts', 'open_questions', 'artifact_refs', 'progress')

_LABELS = {'user_goal': '用户目标', 'file_scope': '文件范围',
           'exclusions': '排除项', 'permission_limits': '权限限制',
           'confirmed_facts': '已确认事实', 'open_questions': '未决问题',
           'artifact_refs': 'Artifact 引用', 'progress': '当前进度'}


def source_fingerprint(entries):
    canonical = json.dumps([(e.id, e.entry_type, e.payload) for e in entries],
                           ensure_ascii=False, sort_keys=True)
    return sha256(canonical.encode('utf-8')).hexdigest()


def extract_key_items(entries, *, bindings=(), permission_mode='', facts=()):
    items = {'user_goal': '', 'file_scope': [], 'exclusions': [],
             'permission_limits': permission_mode, 'confirmed_facts': [],
             'open_questions': [], 'artifact_refs': [], 'progress': ''}
    for entry in entries:
        payload = entry.payload or {}
        if entry.entry_type == 'user_message':
            if not items['user_goal'] and payload.get('text'):
                items['user_goal'] = payload['text']
            items['exclusions'].extend(payload.get('excluded') or [])
        elif entry.entry_type == 'assistant_message':
            text = payload.get('text') or ''
            if text:
                items['progress'] = text[:200]
            items['open_questions'].extend(payload.get('open_questions') or [])
            if '？' in text:
                items['open_questions'].append(text[:100])
        elif entry.entry_type == 'tool_result':
            result = payload.get('result')
            if isinstance(result, dict):
                items['artifact_refs'].extend(
                    a.get('name') for a in result.get('artifacts', [])
                    if isinstance(a, dict) and a.get('name'))
    items['file_scope'] = sorted({b['file_id'] for b in bindings})
    items['confirmed_facts'] = [f"{f['fact_key']}={f['value']}" for f in facts]
    return items


def default_summary(items, entries):
    lines = [f'【压缩摘要】以下 {len(entries)} 条历史消息已压缩，关键约束如下。']
    for key in KEY_ITEMS:
        value = items.get(key)
        if value:
            rendered = value if isinstance(value, str) else json.dumps(
                value, ensure_ascii=False)
            lines.append(f'{_LABELS[key]}：{rendered}')
    return {'text': '\n'.join(lines), 'key_items': dict(items)}


def compact_lane(repo, session_id, lane_id, *, end_entry_id,
                 permission_mode='', summarizer=None):
    history = list(repo.lane_history(session_id, lane_id))
    ids = [e.id for e in history]
    if end_entry_id not in ids:
        raise ValueError('压缩边界不属于该 lane')
    source = history[:ids.index(end_entry_id) + 1]
    if len(source) < 2:
        raise ValueError('压缩范围至少需要两条消息')
    project_id = repo.session_project_id(session_id)
    facts = repo.facts(project_id, status='confirmed')
    bindings = []
    for operation_id in {e.operation_id for e in source if e.operation_id}:
        bindings.extend(repo.operation_files(operation_id))
    items = extract_key_items(source, bindings=bindings,
                              permission_mode=permission_mode, facts=facts)
    produced = (summarizer or default_summary)(items, source)
    missing = [key for key in KEY_ITEMS
               if items.get(key)
               and produced.get('key_items', {}).get(key) != items.get(key)]
    if missing:
        return {'valid': False, 'missing': missing}  # 无效压缩：不保存不替换
    summary_entry = repo.append_entry(
        session_id, lane_id, 'context_summary',
        {'text': produced['text'], 'key_items': produced['key_items'],
         'compacted': True})
    compaction_id = repo.save_compaction(
        session_id, lane_id, source_start_entry_id=source[0].id,
        source_end_entry_id=end_entry_id,
        source_sha256=source_fingerprint(source),
        summary_entry_id=summary_entry.id)
    return {'valid': True, 'compaction_id': compaction_id,
            'key_items': produced['key_items'], 'missing': []}
