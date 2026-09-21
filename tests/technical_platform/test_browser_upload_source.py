import json
from hashlib import sha256
from threading import Event

import pytest

from asset_based_agent.technical_platform.store import PlatformStore


def source(tmp_path, kind='generation'):
    store = PlatformStore(tmp_path / 'state.sqlite', 'alice')
    project = store.create_project('synthetic')
    session = store.create_session(project)
    run = store.start_run(session, {'files': []})
    store.transition(run, 'running', 'synthetic')
    store.transition(run, 'validating', 'synthetic')
    path = tmp_path / 'runs' / run / 'output' / 'sample.docx'
    path.parent.mkdir(parents=True)
    path.write_bytes(b'synthetic artifact, not a business document')
    version = sha256(path.read_bytes()).hexdigest()
    result = {'kind': 'generation', 'ok': True,
              'artifacts': [{'path': str(path), 'name': path.name, 'sha256': version}]}
    if kind == 'review':
        result = {'kind': 'review', 'exported_report': str(path),
                  'delivery_versions': {str(path): {'sha256': version, 'size': path.stat().st_size}}}
    store.save_result(run, result)
    store.transition(run, 'succeeded', 'synthetic')
    return store, session, run, path, version


@pytest.mark.parametrize('kind', ['generation', 'review'])
def test_resolve_only_versioned_successful_deliverable(tmp_path, kind):
    from asset_based_agent.technical_platform.browser_upload_source import (
        resolve_upload_source,
    )
    store, session, run, path, version = source(tmp_path, kind)
    ref = {'run_id': run, 'kind': kind, 'index': 0, 'sha256': version}
    result = resolve_upload_source(store, session, ref, Event())
    assert result['path'] == str(path)
    assert result['sha256'] == version
    assert result['size'] == path.stat().st_size
    assert 'path' not in ref


@pytest.mark.parametrize('case', ['session', 'failed', 'raw', 'changed', 'version', 'path', 'cancel'])
def test_upload_rejects_unbound_original_or_changed_source(tmp_path, case):
    from asset_based_agent.technical_platform.browser_upload_source import (
        resolve_upload_source,
    )
    store, session, run, path, version = source(tmp_path)
    ref = {'run_id': run, 'kind': 'generation', 'index': 0, 'sha256': version}
    cancel = Event()
    if case == 'session': session = 'other'
    if case == 'failed':
        with store.connect() as db: db.execute("UPDATE runs SET state='failed' WHERE id=?", (run,))
    if case == 'raw': store.add_file(store.session(session)['project'], path, version)
    if case == 'changed': path.write_bytes(b'changed')
    if case == 'version': ref['sha256'] = '0' * 64
    if case == 'path': ref['path'] = str(path)
    if case == 'cancel': cancel.set()
    with pytest.raises((ValueError, PermissionError, InterruptedError)):
        resolve_upload_source(store, session, ref, cancel)


@pytest.mark.parametrize('case', ['missing_version', 'negative_index', 'wrong_kind', 'invalid_step'])
def test_upload_requires_explicit_supported_delivery_reference(tmp_path, case):
    from asset_based_agent.technical_platform.browser_upload_source import (
        resolve_upload_source,
    )
    store, session, run, path, version = source(tmp_path, 'review')
    ref = {'run_id': run, 'kind': 'review', 'index': 0, 'sha256': version}
    if case == 'missing_version':
        with store.connect() as db:
            db.execute('UPDATE runs SET result=? WHERE id=?',
                       (json.dumps({'kind': 'review', 'exported_report': str(path)}), run))
    if case == 'negative_index': ref['index'] = -1
    if case == 'wrong_kind': ref['kind'] = 'generation'
    if case == 'invalid_step': ref['step_index'] = -1
    with pytest.raises((ValueError, PermissionError)):
        resolve_upload_source(store, session, ref, Event())


def test_upload_resolves_validated_compound_generation_step(tmp_path):
    from test_artifact_registry import workflow

    from asset_based_agent.technical_platform.adapters.generation import (
        GenerationAdapter,
    )
    from asset_based_agent.technical_platform.adapters.review import ReviewAdapter
    from asset_based_agent.technical_platform.browser_upload_source import (
        resolve_upload_source,
    )
    from asset_based_agent.technical_platform.harness import execute_plan
    from asset_based_agent.technical_platform.plan_results import completed_step_results
    from asset_based_agent.technical_platform.tool_dispatcher import ToolDispatcher

    store, run, plan = workflow(tmp_path, compound_generation=True)
    dispatcher = ToolDispatcher({
        'history.generate': GenerationAdapter(store, run, progress=lambda _: None),
        'preflight.execute': ReviewAdapter(store, run, progress=lambda _: None)})
    assert execute_plan(store, run, plan, dispatcher, Event()) == 'succeeded'
    session = store.run(run)['session']
    records = completed_step_results(store, session, run)
    artifact = records[1]['result']['artifacts'][0]
    ref = {'run_id': run, 'kind': 'generation', 'step_index': 1,
           'index': 0, 'sha256': artifact['sha256']}
    actual = resolve_upload_source(store, session, ref, Event())
    assert actual['path'] == artifact['path']
    ref['step_index'] = 2  # A preflight output is not a generated deliverable.
    with pytest.raises(PermissionError):
        resolve_upload_source(store, session, ref, Event())


@pytest.mark.parametrize('kind', ['generation', 'review'])
def test_oversized_upload_rejected_before_hashing(tmp_path, monkeypatch, kind):
    from asset_based_agent.technical_platform import browser_upload_source as module
    store, session, run, path, version = source(tmp_path, kind)
    with path.open('r+b') as stream:
        stream.truncate(64 * 1024 * 1024 + 1)
    def forbidden_hash(*args):
        pytest.fail('Oversized upload must be rejected before reading its contents')
    monkeypatch.setattr(module, 'fingerprint_download', forbidden_hash)
    ref = {'run_id': run, 'kind': kind, 'index': 0, 'sha256': version}
    with pytest.raises(ValueError, match='size'):
        module.resolve_upload_source(store, session, ref, Event())
