"""Native candidate discovery; call off the GUI thread, never scan arbitrary files."""
import json

from ..browser_contracts import UploadArtifact
from .browser_upload_source import resolve_upload_source


def _references(run, result, step_index=None):
    base = {'run_id': run, 'kind': result.get('kind')}
    if step_index is not None:
        base['step_index'] = step_index
    if result.get('kind') == 'generation' and result.get('ok') is True:
        for index, artifact in enumerate(result.get('artifacts', [])):
            yield {**base, 'index': index, 'sha256': artifact['sha256']}
    elif result.get('kind') == 'review':
        paths = ([result['exported_report']] if result.get('exported_report') else [])
        paths += [path for batch in result.get('annotations', []) for path in batch['files']]
        versions = result.get('delivery_versions', {})
        for index, path in enumerate(paths):
            version = versions.get(path)
            if isinstance(version, dict) and version.get('sha256'):
                yield {**base, 'index': index, 'sha256': version['sha256']}


def collect_upload_candidates(store, session_id, cancel):
    """Return native references plus validated metadata; this grants no upload permission."""
    if cancel.is_set():
        raise InterruptedError('Candidate discovery cancelled')
    records: list[dict] = []
    for run in reversed(store.runs(session_id)):
        if cancel.is_set():
            raise InterruptedError('Candidate discovery cancelled')
        if run['state'] != 'succeeded':
            continue
        try:
            result = json.loads(run['result'] or '{}')
            references = list(_references(run['id'], result))
            if result.get('kind') == 'plan':
                from .plan_results import completed_step_results
                from .review_delivery import step_review_store
                for index, step in enumerate(completed_step_results(store, session_id, run['id'])):
                    value = step['result']
                    if value.get('kind') == 'review':
                        view = step_review_store(store, session_id, run['id'], index)
                        value = json.loads(view.run(run['id'])['result'])
                    references.extend(_references(run['id'], value, index))
            for reference in references:
                if cancel.is_set():
                    raise InterruptedError('Candidate discovery cancelled')
                try:
                    actual = resolve_upload_source(store, session_id, reference, cancel)
                    metadata = UploadArtifact(id=f'upload-{len(records)}', name=actual['name'],
                                              size=actual['size'], sha256=actual['sha256'])
                except InterruptedError:
                    raise
                except (ValueError, OSError, KeyError, TypeError):
                    continue
                records.append({'artifact': metadata.model_dump(), 'source': reference})
        except InterruptedError:
            raise
        except (ValueError, OSError, KeyError, TypeError):
            continue
    if cancel.is_set():
        raise InterruptedError('Candidate discovery cancelled')
    return records
