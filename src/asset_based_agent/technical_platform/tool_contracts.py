"""Trusted adapter declarations, not arbitrary model-defined code entry points."""
from dataclasses import dataclass


@dataclass(frozen=True)
class ToolContract:
    id: str
    skill_id: str
    version: int
    writes_copy: bool
    may_call_model: bool
    resource: str
    retry_policy: str
    cancellation: str
    result_kind: str
    acceptance_gates: tuple[str, ...]


_READ_GATES = ('visible_content_only', 'original_hash_unchanged')
_GENERATE_GATES = ('source_evidence', 'output_validation', 'original_hash_unchanged')
TOOLS = (
    ToolContract('preflight.execute', 'review.preflight', 1, False, False, 'files',
                 'new_run_only', 'file_boundaries', 'preflight', _READ_GATES),
    ToolContract('review.execute', 'report.review', 1, False, True, 'model',
                 'query_remote_state_first', 'local_token_and_remote_cancel', 'review', _READ_GATES),
    ToolContract('detail.generate', 'valuation-detail-workbook-fill', 1, True, True, 'office',
                 'new_run_only', 'owned_worker_only', 'generation', _GENERATE_GATES),
    ToolContract('history.generate', 'gongshang-change-history-docx', 1, True, False, 'files',
                 'new_run_only', 'owned_worker_only', 'generation', _GENERATE_GATES),
    ToolContract('financial-brief.generate', 'financial-brief-docx', 1, True, False, 'office',
                 'new_run_only', 'owned_worker_only', 'generation', _GENERATE_GATES),
    ToolContract('workflow-skill.validate', 'office-workflow-to-skill', 1, True, False, 'files',
                 'new_run_only', 'owned_worker_only', 'generation', _GENERATE_GATES),
    ToolContract('browser.execute', 'browser.task', 1, False, True, 'browser',
                 'query_site_state_first', 'tab_lease_and_local_token', 'browser',
                 ('browser_scope', 'action_receipts', 'site_outcome_verified')),
)


def tool_contract(identity):
    for tool in TOOLS:
        if tool.id == identity:
            return tool
    raise ValueError('Unknown tool')


def skill_tool(skill_id):
    for tool in TOOLS:
        if tool.skill_id == skill_id:
            return tool
    raise ValueError('No tool adapter for skill')
