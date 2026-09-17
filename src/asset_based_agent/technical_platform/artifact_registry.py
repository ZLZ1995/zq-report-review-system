"""Resolve scoped source files and verified producer artifacts, never model paths."""
import json
from pathlib import Path

from .execution_plan import ExecutionPlan
from .generation_paths import generation_work_directory
from .skills import digest
from .step_results import StepResults
from .tool_dispatcher import ToolOutcome


def resolve_step_inputs(store, run_id, step):
    run = store.run(run_id)
    snapshot = json.loads(run['snapshot'])
    with store.connect() as db:
        registered = db.execute('SELECT plan_json FROM execution_plans WHERE run=?', (run_id,)).fetchone()
        states = {row['step_id']: dict(row) for row in db.execute(
            'SELECT * FROM execution_steps WHERE run=?', (run_id,))}
    if registered is None:
        raise PermissionError('Plan has not been registered')
    plan = ExecutionPlan.model_validate_json(registered[0])
    by_step = {item.step_id: item for item in plan.steps}
    if by_step.get(step.step_id) != step or step.identity.task_id != run_id:
        raise PermissionError('Input request does not match the registered step')
    sources = {item['id']: item for item in snapshot['files']}
    available = {item['id']: item for item in store.files(plan.identity.project_id)}
    producers = {item.output_ref: item for item in plan.steps}
    ancestors, pending = set(), list(step.dependencies)
    while pending:
        identity = pending.pop()
        if identity not in ancestors:
            ancestors.add(identity)
            pending.extend(by_step[identity].dependencies)
    resolved = []
    for reference in step.inputs:
        if reference in sources:
            source = sources[reference]
            if available.get(reference) != source or plan.input_versions.get(reference) != source['sha256']:
                raise PermissionError('Source file changed or is outside the plan')
            resolved.append(source)
            continue
        producer = producers.get(reference)
        if producer is None or producer.step_id not in ancestors:
            raise PermissionError('Artifact is not produced by an authorized dependency')
        state = states.get(producer.step_id)
        if state is None or state['state'] != 'succeeded' or not state['checkpoint_json']:
            raise PermissionError('Producer has no validated successful result')
        outcome = ToolOutcome.model_validate_json(state['checkpoint_json'])
        if outcome.step_id != producer.step_id or outcome.status != 'succeeded' or outcome.result_ref is None:
            raise PermissionError('Producer result is not usable')
        result = StepResults(store).read(run_id, producer.step_id, outcome.result_ref)
        expected_name = {'history.generate': 'history_fragment.docx',
                         'detail.generate': 'detail_workbook.xlsx'}.get(producer.tool)
        if expected_name is None or result.get('kind') != 'generation' or result.get('ok') is not True:
            raise PermissionError('Dependency does not produce a supported document artifact')
        items = [item for item in result.get('artifacts', []) if item.get('name') == expected_name]
        if len(items) != 1:
            raise ValueError('Primary artifact is missing or ambiguous')
        item = items[0]
        root = (generation_work_directory(store.path.parent, run_id,
                    producer.step_id if snapshot.get('mode') == 'compound' else None) / 'output')
        path = Path(item['path']).resolve()
        if not path.is_relative_to(root) or path.name != expected_name:
            raise PermissionError('Artifact path is outside the producer output directory')
        if not path.is_file() or digest(path) != item['sha256']:
            raise ValueError('Artifact changed after producer validation')
        resolved.append({'id': 'artifact-' + outcome.result_ref, 'name': expected_name,
                         'path': str(path), 'sha256': item['sha256'], 'size': path.stat().st_size})
    if len({item['id'] for item in resolved}) != len(resolved):
        raise ValueError('Step input resolves to duplicate files')
    return resolved
