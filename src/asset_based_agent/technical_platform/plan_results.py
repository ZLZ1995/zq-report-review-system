"""Read verified step results and resolve local artifact links by ordinal."""
import json
from pathlib import Path

from .execution_plan import ExecutionPlan
from .generation_paths import generation_work_directory
from .skills import digest
from .step_results import StepResults
from .tool_dispatcher import ToolOutcome


def completed_step_results(store, session_id, run_id):
    run = store.run(run_id)
    if run['session'] != session_id or run['state'] != 'succeeded':
        raise PermissionError('Plan result is not available in this session')
    result = json.loads(run['result'] or '{}')
    snapshot = json.loads(run['snapshot'])
    plan = ExecutionPlan.model_validate(snapshot['execution_plan'])
    if snapshot.get('mode') != 'compound' or result.get('kind') != 'plan':
        raise ValueError('Not a compound plan result')
    with store.connect() as db:
        states = {r['step_id']: dict(r) for r in db.execute(
            'SELECT step_id,state,checkpoint_json FROM execution_steps WHERE run=?', (run_id,))}
    records = []
    for step in plan.steps:
        state = states[step.step_id]
        outcome = ToolOutcome.model_validate_json(state['checkpoint_json'])
        if (state['state'] != 'succeeded' or outcome.status != 'succeeded'
                or outcome.step_id != step.step_id or not outcome.result_ref
                or result['steps'].get(step.step_id) != outcome.model_dump()):
            raise PermissionError('Step result differs from its completion checkpoint')
        records.append({'step_id': step.step_id, 'goal': step.goal,
                        'result': StepResults(store).read(run_id, step.step_id, outcome.result_ref)})
    return records


def step_artifact_path(store, session_id, run_id, step_index, artifact_index):
    records = completed_step_results(store, session_id, run_id)
    if type(step_index) is not int or not 0 <= step_index < len(records):
        raise ValueError('Invalid step index')
    record = records[step_index]
    result = record['result']
    artifacts = result.get('artifacts', [])
    if (result.get('kind') != 'generation' or result.get('ok') is not True
            or type(artifact_index) is not int or not 0 <= artifact_index < len(artifacts)):
        raise ValueError('Invalid artifact index')
    item = artifacts[artifact_index]
    path = Path(item['path']).resolve()
    root = generation_work_directory(store.path.parent, run_id, record['step_id']) / 'output'
    if (not path.is_relative_to(root) or path.name != item['name']
            or path.suffix.lower() not in {'.docx', '.xlsx', '.json', '.md'}):
        raise PermissionError('Artifact is outside its step')
    if not path.is_file() or digest(path) != item['sha256']:
        raise ValueError('Artifact changed or is no longer available')
    return path
