"""Use the real visibility-filtered read-only reviewer as a lifecycle-neutral step."""
import json
from hashlib import sha256

from ..artifact_registry import resolve_step_inputs
from ..context import model_request
from ..permissions import PermissionService
from ..skills import preflight
from ..step_results import StepResults
from ..tool_dispatcher import ToolOutcome


class ReviewAdapter:
    def __init__(self, store, run_id, *, progress, provider=None, output=None, review_function=preflight):
        self.store, self.run_id = store, run_id
        self.progress, self.provider, self.output = progress, provider, output
        self.review_function = review_function

    def __call__(self, step, dependencies, cancel):
        PermissionService(self.store).verify(self.run_id)
        snapshot = json.loads(self.store.run(self.run_id)['snapshot'])
        if step.identity.task_id != self.run_id or step.tool not in {'preflight.execute', 'review.execute'}:
            raise PermissionError('Review adapter scope mismatch')
        files = resolve_step_inputs(self.store, self.run_id, step)
        reference_ids = {f['id'] for reference, f in zip(step.inputs, files)
                         if reference in step.reference_inputs}
        remote = step.tool == 'review.execute'
        if remote != (self.provider is not None):
            raise PermissionError('Model provider does not match step action')
        if remote:
            if (snapshot['permissions'].get('call_model') is not True
                    or self.provider.model_id != snapshot.get('model')
                    or sha256(self.provider.skill_instructions.encode('utf-8')).hexdigest() != step.rules_sha256):
                raise PermissionError('Review model or rules changed')
            self.provider.cancel_event = cancel
            self.provider.user_request = (model_request(snapshot['user_request'], snapshot['execution_context'])
                                          if 'execution_context' in snapshot else snapshot['user_request'])
            if step.goal:
                self.provider.user_request += '\n本步骤仅执行以下目标（不要执行其他步骤）：\n' + step.goal
            if step.constraints:
                self.provider.user_request += '\n必须遵守的本轮限制：\n' + '\n'.join(step.constraints)
        result = self.review_function(self.store, self.run_id, cancel, self.progress,
                           provider=self.provider, output=self.output, claimed=True,
                           manage_run=False, selected_files=files,
                           client_job_id=f'PLATFORM-{self.run_id}-{step.step_id}',
                           **({'reference_file_ids': reference_ids} if reference_ids else {}))
        if cancel.is_set() or result.get('kind') == 'cancelled':
            return ToolOutcome(step_id=step.step_id, status='cancelled')
        reference = StepResults(self.store).save(self.run_id, step.step_id, result)
        return ToolOutcome(step_id=step.step_id, status='succeeded',
                           passed_gates=['visible_content_only', 'original_hash_unchanged'], result_ref=reference)
