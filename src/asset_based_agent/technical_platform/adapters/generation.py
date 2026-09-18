"""Wrap the existing locked-template generator without taking over run state."""
import json
from hashlib import sha256
from pathlib import Path

from ..artifact_registry import resolve_step_inputs
from ..generation_paths import generation_work_directory
from ..permissions import PermissionService
from ..skills import FINANCIAL_BRIEF, HISTORY, WORKFLOW_TO_SKILL, digest
from ..step_results import StepResults
from ..tool_dispatcher import ToolOutcome


class GenerationAdapter:
    def __init__(self, store, run_id, *, progress, provider=None):
        self.store, self.run_id = store, run_id
        self.progress, self.provider = progress, provider

    def __call__(self, step, dependencies, cancel):
        from ..generation import execute_generation

        PermissionService(self.store).verify(self.run_id)
        snapshot = json.loads(self.store.run(self.run_id)['snapshot'])
        compound = snapshot.get('mode') == 'compound'
        if compound:
            files = resolve_step_inputs(self.store, self.run_id, step)
            config = snapshot.get('step_configs', {}).get(step.step_id)
            if (not isinstance(config, dict) or set(config) != {
                    'skill_instructions', 'input_roles', 'automatic_materials'}
                    or type(config['automatic_materials']) is not bool
                    or not isinstance(config['skill_instructions'], str)
                    or step.reference_inputs):
                raise PermissionError('Generation step configuration is invalid')
            references = dict(zip(step.inputs, (f['id'] for f in files)))
            roles = config['input_roles']
            if roles is not None:
                if not isinstance(roles, dict) or not set(roles.values()) <= set(references):
                    raise PermissionError('Generation input role is outside the step')
                roles = {key: references[value] for key, value in roles.items()}
            snapshot = {**snapshot, 'mode': 'local_generation', 'skill_id': step.skill_id,
                        'files': files, 'input_roles': roles,
                        'automatic_materials': config['automatic_materials'],
                        'skill_instructions': config['skill_instructions'],
                        'skill_rules_sha256': sha256(config['skill_instructions'].encode()).hexdigest(),
                        'capabilities': ['generate_artifacts', 'read_selected_files']}
        if (step.identity.task_id != self.run_id or step.skill_id != snapshot['skill_id']
                or (not compound and (
                    step.step_id != 'execute' or step.inputs != [item['id'] for item in snapshot['files']]))
                or step.tool not in {'detail.generate', 'history.generate', 'financial-brief.generate',
                                     'workflow-skill.validate'}
                or step.rules_sha256 != snapshot['skill_rules_sha256']
                or snapshot['permissions'].get('generate_artifacts') is not True):
            raise PermissionError('Generation step differs from confirmed task')
        automatic = snapshot.get('automatic_materials') is True
        if automatic != (self.provider is not None):
            raise PermissionError('Generation model mode differs from confirmed task')
        if automatic and (self.provider.model_id != snapshot['model'] or
                          sha256(self.provider.skill_instructions.encode('utf-8')).hexdigest() != step.rules_sha256):
            raise PermissionError('Generation model or rules changed')
        result = execute_generation(self.store, self.run_id, snapshot, cancel, self.progress,
                                    provider=self.provider, manage_run=False,
                                    **({'step_id': step.step_id} if compound else {}))
        if cancel.is_set():
            return ToolOutcome(step_id=step.step_id, status='cancelled')
        if result.get('kind') != 'generation' or type(result.get('ok')) is not bool:
            raise ValueError('Generator returned an invalid result')
        artifacts = result.get('artifacts', [])
        if result['ok']:
            primary = ('history_fragment.docx' if step.skill_id == HISTORY.id else
                       'financial_brief.docx' if step.skill_id == FINANCIAL_BRIEF.id else
                       'office_workflow_contract_validation.json'
                       if step.skill_id == WORKFLOW_TO_SKILL.id else 'detail_workbook.xlsx')
            if not any(item.get('name') == primary for item in artifacts):
                raise ValueError('Generation did not produce its required artifact')
        elif any(item.get('name') != 'user_feedback.md' for item in artifacts):
            raise ValueError('Failed generation cannot publish business artifacts')
        root = (generation_work_directory(self.store.path.parent, self.run_id,
                                          step.step_id if compound else None) / 'output')
        for item in artifacts:
            path = Path(item['path']).resolve()
            if (not path.is_relative_to(root) or path.name != item['name']
                    or path.suffix.lower() not in {'.docx', '.xlsx', '.pdf', '.png', '.md', '.json'}
                    or not path.is_file() or digest(path) != item['sha256']):
                raise ValueError('Generated artifact location or hash is invalid')
        reference = StepResults(self.store).save(self.run_id, step.step_id, result)
        return ToolOutcome(step_id=step.step_id, status='succeeded' if result['ok'] else 'failed',
                           passed_gates=step.acceptance_gates if result['ok'] else [], result_ref=reference)
