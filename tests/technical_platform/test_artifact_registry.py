import json
import threading

import pytest
from openpyxl import Workbook

from asset_based_agent.technical_platform.execution_plan import ExecutionPlan
from asset_based_agent.technical_platform.permissions import PermissionService
from asset_based_agent.technical_platform.skills import HISTORY, digest
from asset_based_agent.technical_platform.store import PlatformStore
from asset_based_agent.technical_platform.task_spec import build_task_spec


def workflow(tmp_path, *, compound_generation=False):
    store = PlatformStore(tmp_path / 'state.sqlite', 'alice')
    project = store.create_project('synthetic')
    session = store.create_session(project)
    source = tmp_path / 'source.xlsx'
    book = Workbook()
    book.active.title = '变更信息'
    book.active.append(['变更日期', '变更事项', '变更前', '变更后'])
    book.active.append(['2026-01-01', '法定代表人变更', '张甲', '李乙'])
    book.save(source)
    store.add_file(project, source, digest(source))
    files = store.files(project)
    snapshot = build_task_spec(store, session, 'generate then inspect only the generated document', HISTORY,
                               files, input_roles={'source_excel': files[0]['id']}, generation_confirmed=True).to_snapshot()
    first = snapshot['execution_plan']['steps'][0]
    snapshot['execution_plan']['steps'].append({
        **first, 'step_id': 'inspect', 'tool': 'preflight.execute', 'skill_id': 'review.preflight',
        'skill_version': '0.1.0', 'inputs': [first['output_ref']], 'dependencies': ['execute'],
        'output_ref': 'inspection', 'acceptance_gates': ['visible_content_only', 'original_hash_unchanged']})
    if compound_generation:
        second = {**first, 'step_id': 'second', 'dependencies': ['execute'], 'output_ref': 'second-result'}
        snapshot['execution_plan']['steps'].insert(1, second)
        snapshot['execution_plan']['steps'][2].update(inputs=['second-result'], dependencies=['second'])
        snapshot['mode'] = 'compound'
        snapshot['step_configs'] = {name: {
            'skill_instructions': snapshot['skill_instructions'], 'input_roles': snapshot['input_roles'],
            'automatic_materials': False} for name in ('execute', 'second')}
    run = store.start_run(session, snapshot)
    PermissionService(store).authorize(run, snapshot, confirmed=True)
    return store, run, ExecutionPlan.model_validate(snapshot['execution_plan'])


@pytest.mark.parametrize('tamper', [False, True])
def test_real_generation_then_inspection_reads_only_verified_artifact(tmp_path, tamper):
    from pathlib import Path

    from asset_based_agent.technical_platform.adapters.generation import (
        GenerationAdapter,
    )
    from asset_based_agent.technical_platform.adapters.review import ReviewAdapter
    from asset_based_agent.technical_platform.harness import execute_plan
    from asset_based_agent.technical_platform.step_results import StepResults
    from asset_based_agent.technical_platform.tool_dispatcher import ToolDispatcher
    store, run, plan = workflow(tmp_path)
    source = tmp_path / 'source.xlsx'
    source_hash = digest(source)
    generator = GenerationAdapter(store, run, progress=lambda _: None)
    def generate(step, dependencies, cancel):
        outcome = generator(step, dependencies, cancel)
        if tamper:
            result = StepResults(store).read(run, step.step_id, outcome.result_ref)
            Path(result['artifacts'][0]['path']).write_bytes(b'synthetic corruption')
        return outcome
    dispatcher = ToolDispatcher({'history.generate': generate,
                                 'preflight.execute': ReviewAdapter(store, run, progress=lambda _: None)})
    status = execute_plan(store, run, plan, dispatcher, threading.Event())
    assert status == ('failed' if tamper else 'succeeded')
    assert digest(source) == source_hash
    with store.connect() as db:
        states = dict(db.execute('SELECT step_id,state FROM execution_steps WHERE run=?', (run,)))
        assert states['execute'] == 'succeeded'
        assert states['inspect'] == ('failed' if tamper else 'succeeded')
        if tamper:
            assert db.execute('SELECT COUNT(*) FROM execution_results WHERE run=? AND step_id=?',
                              (run, 'inspect')).fetchone()[0] == 0
    if not tamper:
        outcomes = json.loads(store.run(run)['result'])['steps']
        result = StepResults(store).read(run, 'inspect', outcomes['inspect']['result_ref'])
        assert [item['name'] for item in result['files']] == ['history_fragment.docx']
        assert result['files'][0]['chunks'] > 0


def test_registry_rejects_another_owner_and_unregistered_step(tmp_path):
    from asset_based_agent.technical_platform.artifact_registry import (
        resolve_step_inputs,
    )
    store, run, plan = workflow(tmp_path)
    with pytest.raises(PermissionError):
        resolve_step_inputs(PlatformStore(store.path, 'bob'), run, plan.steps[1])
    with pytest.raises(PermissionError):
        resolve_step_inputs(store, run, plan.steps[1])


def test_registry_rejects_pending_producer_and_forged_consumer(tmp_path):
    from asset_based_agent.technical_platform.artifact_registry import (
        resolve_step_inputs,
    )
    from asset_based_agent.technical_platform.event_store import ExecutionStore

    store, run, plan = workflow(tmp_path)
    store.claim_run(run)
    ExecutionStore(store).register(plan)
    with pytest.raises(PermissionError, match='successful result'):
        resolve_step_inputs(store, run, plan.steps[1])
    forged = plan.steps[1].model_copy(update={'inputs': plan.steps[0].inputs})
    with pytest.raises(PermissionError, match='registered step'):
        resolve_step_inputs(store, run, forged)


@pytest.mark.parametrize('misroute', [False, True])
def test_two_real_generators_use_isolated_step_directories_then_inspect_second(tmp_path, monkeypatch, misroute):
    from pathlib import Path

    from asset_based_agent.technical_platform import generation
    from asset_based_agent.technical_platform.adapters.generation import (
        GenerationAdapter,
    )
    from asset_based_agent.technical_platform.adapters.review import ReviewAdapter
    from asset_based_agent.technical_platform.harness import execute_plan
    from asset_based_agent.technical_platform.step_results import StepResults
    from asset_based_agent.technical_platform.tool_dispatcher import ToolDispatcher
    store, run, plan = workflow(tmp_path, compound_generation=True)
    original = generation.execute_generation
    generated = []
    def generate(*args, **kwargs):
        if misroute and kwargs.get('step_id') == 'second':
            return generated[0]
        result = original(*args, **kwargs)
        generated.append(result)
        return result
    monkeypatch.setattr(generation, 'execute_generation', generate)
    dispatcher = ToolDispatcher({'history.generate': GenerationAdapter(store, run, progress=lambda _: None),
                                 'preflight.execute': ReviewAdapter(store, run, progress=lambda _: None)})
    assert execute_plan(store, run, plan, dispatcher, threading.Event()) == ('failed' if misroute else 'succeeded')
    with store.connect() as db:
        ids = dict(db.execute('SELECT step_id,id FROM execution_results WHERE run=?', (run,)))
    if misroute:
        assert set(ids) == {'execute'}
        return
    results = StepResults(store)
    first = results.read(run, 'execute', ids['execute'])
    second = results.read(run, 'second', ids['second'])
    first_path, second_path = [Path(r['artifacts'][0]['path']) for r in (first, second)]
    assert first_path != second_path
    assert first_path.is_file() and second_path.is_file()
    assert digest(first_path) == first['artifacts'][0]['sha256']
    assert digest(second_path) == second['artifacts'][0]['sha256']
    inspected = results.read(run, 'inspect', ids['inspect'])
    assert [f['name'] for f in inspected['files']] == ['history_fragment.docx']
