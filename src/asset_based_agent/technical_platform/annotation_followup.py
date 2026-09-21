"""Persist annotation questions atomically without opening dialogs or writing files."""
import json

from .annotations import annotation_offer
from .plan_results import completed_step_results
from .store import now


def ensure_questions(store, run_id, *, step_indices=None):
    added = []
    with store.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        row = db.execute(
            'SELECT r.* FROM runs r JOIN sessions s ON s.id=r.session '
            'JOIN projects p ON p.id=s.project WHERE r.id=? AND p.owner=?',
            (run_id, store.owner),
        ).fetchone()
        if row is None:
            raise PermissionError('Review task is not owned by this account')
        if row['state'] != 'succeeded':
            return []
        result = json.loads(row['result'] or '{}')
        if result.get('kind') == 'plan':
            records = completed_step_results(store, row['session'], run_id)
            candidates = [(ordinal, item['step_id'], item['result'])
                          for ordinal, item in enumerate(records)
                          if item['result'].get('kind') == 'review']
        else:
            candidates = [(None, None, result)]
        for ordinal, step_id, review in candidates:
            if step_indices is not None and ordinal not in step_indices:
                continue
            if not annotation_offer(row['state'], review):
                continue
            if step_id is None:
                metadata = result
            else:
                deliveries = result.setdefault('review_deliveries', {})
                if not isinstance(deliveries, dict):
                    raise ValueError('Invalid review delivery metadata')
                metadata = deliveries.setdefault(step_id, {})
                if (not isinstance(metadata, dict) or not set(metadata) <= {
                        'exported_report', 'annotations', 'annotation_prompted', 'delivery_versions'}):
                    raise ValueError('Invalid review delivery metadata')
            if metadata.get('annotation_prompted'):
                continue
            metadata['annotation_prompted'] = True
            label = f'第 {ordinal + 1} 个步骤：' if ordinal is not None else ''
            message = (f'任务 {run_id}\n\n' + label +
                       '是否生成带问题标记和批注的文件副本？原始文件不会修改。'
                       '可通过下方批注入口生成，也可以暂不生成。')
            db.execute('INSERT INTO messages(session,role,text,created) VALUES(?,?,?,?)',
                       (row['session'], 'assistant', message, now()))
            added.append(ordinal)
        if added:
            db.execute('UPDATE runs SET result=? WHERE id=?',
                       (json.dumps(result, ensure_ascii=False), run_id))
    return added
