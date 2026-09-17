import json
import threading

import pytest
from openpyxl import Workbook

from asset_based_agent.technical_platform.execution import execute_task
from asset_based_agent.technical_platform.permissions import PermissionService
from asset_based_agent.technical_platform.skills import (
    HISTORY,
    PREFLIGHT,
    REVIEW,
    digest,
)
from asset_based_agent.technical_platform.store import PlatformStore


def prepared(tmp_path, *, remote=False):
    from asset_based_agent.technical_platform.compound_task import (
        build_compound_task_spec,
    )
    store = PlatformStore(tmp_path / 'db.sqlite', 'alice')
    project = store.create_project('synthetic')
    session = store.create_session(project)
    book = Workbook()
    book.active.title = '变更信息'
    book.active.append(['变更日期', '变更事项', '变更前', '变更后'])
    book.active.append(['2026-01-01', '法定代表人变更', '张甲', '李乙'])
    source = tmp_path / 'source.xlsx'
    book.save(source)
    store.add_file(project, source, digest(source))
    files = store.files(project)
    identity = files[0]['id']
    consumer = REVIEW if remote else PREFLIGHT
    request = {'request_id': 'r', 'model_id': 'm', 'message_id': 'msg', 'prompt': '生成后检查生成的文件',
               'files': [{k: files[0][k] for k in ('id', 'name', 'sha256')}],
               'skills': [{'id': s.id, 'adapter': s.id, 'name': s.name, 'description': ''}
                          for s in (HISTORY, consumer)]}
    understanding = {'message_intent': 'execute', 'goal': request['prompt'], 'targets': [identity],
                     'references': [], 'excluded': [], 'constraints': ['不改原件'], 'deliverables': ['Word'],
                     'missing_inputs': [], 'evidence_message_ids': ['msg'],
                     'skill_ids': [HISTORY.id, consumer.id], 'next_action': 'plan', 'reply': '准备生成并检查'}
    proposal = {'request_id': 'r', 'steps': [
        {'step_id': 'generate', 'skill_id': HISTORY.id, 'goal': '生成沿革', 'dependencies': [],
         'inputs': [{'kind': 'file', 'ref': identity, 'role': 'target'}]},
        {'step_id': 'inspect', 'skill_id': consumer.id, 'goal': '检查成果', 'dependencies': ['generate'],
         'inputs': [{'kind': 'step_output', 'ref': 'generate', 'role': 'target'}]}]}
    snapshot = build_compound_task_spec(store, session, {'request': request, 'understanding': understanding},
                                        proposal, files, revision=2).to_snapshot()
    return store, session, snapshot


def test_public_entry_executes_compiled_real_generation_and_preflight(tmp_path):
    from asset_based_agent.technical_platform.step_results import StepResults
    store, session, snapshot = prepared(tmp_path)
    assert snapshot['file_scope']['revision'] == 2
    assert snapshot['permissions']['call_model'] is False
    assert snapshot['permissions']['generate_artifacts'] is True
    assert snapshot['step_configs']['generate']['input_roles'] == {'source_excel': snapshot['files'][0]['id']}
    run = store.start_run(session, snapshot)
    PermissionService(store).authorize(run, snapshot, confirmed=True)
    result = execute_task(store, run, threading.Event(), lambda _: None)
    assert result['kind'] == 'plan' and set(result['steps']) == {'generate', 'inspect'}
    assert store.run(run)['state'] == 'succeeded'
    inspected = StepResults(store).read(run, 'inspect', result['steps']['inspect']['result_ref'])
    assert [f['name'] for f in inspected['files']] == ['history_fragment.docx']


def test_single_step_compound_keeps_plan_result_for_scoped_delivery(tmp_path):
    from asset_based_agent.technical_platform.compound_task import (
        build_compound_task_spec,
    )
    from asset_based_agent.technical_platform.plan_results import completed_step_results
    store, session, original = prepared(tmp_path)
    payload, proposal = original['planning_request'], original['plan_proposal']
    payload['request']['skills'] = payload['request']['skills'][:1]
    payload['understanding']['skill_ids'] = [HISTORY.id]
    proposal['steps'] = proposal['steps'][:1]
    snapshot = build_compound_task_spec(store, session, payload, proposal,
                                        original['planning_files'], revision=3).to_snapshot()
    run = store.start_run(session, snapshot)
    PermissionService(store).authorize(run, snapshot, confirmed=True)
    result = execute_task(store, run, threading.Event(), lambda _: None)
    assert result['kind'] == 'plan'
    assert completed_step_results(store, session, run)[0]['result']['kind'] == 'generation'


@pytest.mark.parametrize('change', [
    lambda s: s['permissions'].update(call_model=True),
    lambda s: s['step_configs']['generate'].update(automatic_materials=True),
    lambda s: s['execution_plan']['steps'][0].update(goal='different'),
    lambda s: s['file_scope'].update(revision=3),
])
def test_even_authorized_compound_snapshot_must_match_local_compilation(tmp_path, change):
    store, session, snapshot = prepared(tmp_path)
    change(snapshot)
    run = store.start_run(session, snapshot)
    PermissionService(store).authorize(run, snapshot, confirmed=True)
    with pytest.raises((ValueError, PermissionError)):
        execute_task(store, run, threading.Event(), lambda _: None)
    assert store.run(run)['state'] == 'failed'
    assert not (tmp_path / 'runs' / run).exists()
    assert json.loads(store.run(run)['snapshot'])['permissions']['modify_originals'] is False


def test_compound_model_plan_requires_login_before_any_local_step(tmp_path):
    store, session, snapshot = prepared(tmp_path, remote=True)
    run = store.start_run(session, snapshot)
    PermissionService(store).authorize(run, snapshot, confirmed=True)
    with pytest.raises(PermissionError, match='登录'):
        execute_task(store, run, threading.Event(), lambda _: None)
    assert not (tmp_path / 'runs' / run).exists()


def test_compound_real_generation_passes_only_output_to_mock_review(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from asset_based_agent.report_review_app.services import remote_review_llm
    store, session, snapshot = prepared(tmp_path, remote=True)
    calls = []
    class Provider:
        def __init__(self, client, *, model_id, skill_instructions):
            self.model_id, self.skill_instructions = model_id, skill_instructions
        def set_client_job_id(self, identity):
            assert identity.endswith('-inspect')
        def review_batches(self, batches, progress_callback=None):
            chunks = [c for b in batches for c in b.chunks]
            assert chunks and {c.source_file_name for c in chunks} == {'history_fragment.docx'}
            assert '检查成果' in self.user_request and '不改原件' in self.user_request
            calls.append(chunks)
            return []
    monkeypatch.setattr(remote_review_llm, 'RemoteReviewLlm', Provider)
    run = store.start_run(session, snapshot)
    PermissionService(store).authorize(run, snapshot, confirmed=True)
    result = execute_task(store, run, threading.Event(), lambda _: None,
                          client=SimpleNamespace(access_token='synthetic'))
    assert result['kind'] == 'plan' and len(calls) == 1
    assert store.run(run)['state'] == 'succeeded'


def test_compound_requires_receipt_before_generation(tmp_path):
    store, session, snapshot = prepared(tmp_path)
    run = store.start_run(session, snapshot)
    with pytest.raises(PermissionError):
        execute_task(store, run, threading.Event(), lambda _: None)
    assert not (tmp_path / 'runs' / run).exists()
