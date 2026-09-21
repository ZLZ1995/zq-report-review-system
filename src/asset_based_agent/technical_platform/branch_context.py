"""Frozen result references, not inherited instructions or execution authority."""
import json
from contextlib import nullcontext
from hashlib import sha256


def fingerprint(value):
    return sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                             allow_nan=False).encode('utf-8')).hexdigest()


def completed_references(db, session, before):
    rows = db.execute('''SELECT r.id,r.result FROM runs r
        WHERE r.session=? AND r.state='succeeded' AND r.result IS NOT NULL
        AND EXISTS(SELECT 1 FROM events e WHERE e.run=r.id AND e.state='succeeded' AND e.created<=?)
        ORDER BY r.created,r.id LIMIT 101''', (session, before)).fetchall()
    if len(rows) > 100:
        raise ValueError('Branch context exceeds 100 completed results')
    return [{'run_id': row['id'], 'result_sha256': fingerprint(json.loads(row['result']))} for row in rows]


def validate_generated_files(store, session, run_id, result):
    from .delivery_versions import verify_review_deliveries
    from .generation import artifact_path
    from .generation_paths import generation_work_directory
    from .plan_results import completed_step_results, step_artifact_path
    from .skills import digest
    if not isinstance(result, dict):
        raise TypeError('Invalid completed result')
    if result.get('kind') == 'review':
        verify_review_deliveries(result)
    elif result.get('kind') == 'generation':
        if result.get('ok') is not True or not isinstance(result.get('artifacts'), list):
            raise ValueError('Generation was not validated')
        root = generation_work_directory(store.path.parent, run_id) / 'output'
        if root.resolve() != root:
            raise PermissionError('Artifact directory redirected')
        for index, item in enumerate(result['artifacts']):
            path = artifact_path(store, session, run_id, index)
            if path.name != item['name'] or digest(path) != item['sha256']:
                raise ValueError('Referenced artifact changed')
    elif result.get('kind') == 'plan':
        records = completed_step_results(store, session, run_id)
        review_ids = {record['step_id'] for record in records if record['result'].get('kind') == 'review'}
        if not set(result.get('review_deliveries', {})) <= review_ids:
            raise ValueError('Unknown review delivery step')
        for step_index, record in enumerate(records):
            if record['result'].get('kind') == 'review':
                from .review_delivery import step_review_store
                view = step_review_store(store, session, run_id, step_index)
                verify_review_deliveries(json.loads(view.run(run_id)['result']))
            if record['result'].get('kind') == 'generation':
                for index in range(len(record['result'].get('artifacts', []))):
                    step_artifact_path(store, session, run_id, step_index, index)


def read_results(service, identity, *, _db=None, _ancestors=()):
    if identity in _ancestors or len(_ancestors) >= 32:
        raise ValueError('Branch ancestor cycle or depth limit')
    with (service.store.connect() if _db is None else nullcontext(_db)) as db:
        if _db is None:
            db.execute('BEGIN')
        child = service._session(db, identity)
        metadata = db.execute('SELECT * FROM session_metadata WHERE session=?', (identity,)).fetchone()
        if metadata is None or not metadata['parent_session']:
            return []
        parent = service._session(db, metadata['parent_session'])
        if parent['project'] != child['project']:
            raise PermissionError('Branch parent is outside this project')
        message = db.execute('SELECT * FROM messages WHERE id=? AND session=?',
                             (metadata['fork_message'], parent['id'])).fetchone()
        snapshot = json.loads(metadata['context_snapshot'])
        if (message is None or snapshot.get('schema_version') != 1
                or snapshot.get('source_message') != {'id': metadata['fork_message'],
                                                      'sha256': fingerprint(dict(message))}):
            raise ValueError('Branch anchor changed or is unavailable')
        refs = snapshot.get('completed_facts')
        if not isinstance(refs, list) or len(refs) > 100:
            raise ValueError('Invalid branch references')
        results = []
        if snapshot.get('ancestor_snapshot_sha256') is not None:
            ancestor = db.execute('SELECT context_snapshot FROM session_metadata WHERE session=?',
                                  (parent['id'],)).fetchone()
            if (ancestor is None or fingerprint(json.loads(ancestor[0])) != snapshot['ancestor_snapshot_sha256']):
                raise ValueError('Branch ancestor snapshot changed')
            results = read_results(service, parent['id'], _db=db, _ancestors=(*_ancestors, identity))
        seen = {r['run_id'] for r in results}
        if len(results) + len(refs) > 100:
            raise ValueError('Branch context exceeds 100 completed results')
        for ref in refs:
            if (not isinstance(ref, dict) or set(ref) != {'run_id', 'result_sha256'}
                    or not isinstance(ref['run_id'], str) or ref['run_id'] in seen):
                raise ValueError('Invalid branch reference')
            seen.add(ref['run_id'])
            row = db.execute('''SELECT r.result FROM runs r WHERE r.id=? AND r.session=?
                AND r.state='succeeded' AND EXISTS(SELECT 1 FROM events e WHERE e.run=r.id
                AND e.state='succeeded' AND e.created<=?)''',
                             (ref['run_id'], parent['id'], message['created'])).fetchone()
            if row is None or row['result'] is None:
                raise PermissionError('Result was not completed before this branch anchor')
            result = json.loads(row['result'])
            if fingerprint(result) != ref['result_sha256']:
                raise ValueError('Branch result changed; explicit new reference required')
            try:
                validate_generated_files(service.store, parent['id'], ref['run_id'], result)
            except (KeyError, TypeError, IndexError) as exc:
                raise ValueError('Invalid referenced artifact metadata') from exc
            results.append({'run_id': ref['run_id'], 'result': result})
        return results
