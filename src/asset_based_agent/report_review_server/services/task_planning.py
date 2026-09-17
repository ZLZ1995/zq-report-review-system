"""Metered proposal only; local compilation and permission gates remain mandatory."""
import json
from pathlib import Path

try:
    from ...agent_contracts import PlanningRequest, PlanProposal, validate_proposal
except ModuleNotFoundError:  # pragma: no cover - legacy Zeabur build context
    from ..compat_agent_contracts import PlanningRequest, PlanProposal, validate_proposal
from .auth_service import ServiceError
from .provider_gateway import NormalizedUsage


def propose_plan(metered, db, user_id, request: PlanningRequest):
    request = PlanningRequest.model_validate(request.model_dump())
    instructions = Path(__file__).parents[1].joinpath('prompts/task_planning.txt').read_text('utf-8')
    instructions += '\nJSON Schema:\n' + json.dumps(PlanProposal.model_json_schema(), ensure_ascii=False)
    content = request.model_dump_json(exclude={'request': {'model_id'}})
    result = metered.execute(
        db, user_id=user_id, model_id=request.request.model_id,
        client_request_id='plan:' + request.request.request_id,
        estimated_usage=NormalizedUsage(input_tokens=len(instructions) + len(content), output_tokens=8192),
        payload={'messages': [{'role': 'system', 'content': instructions},
                              {'role': 'user', 'content': content}],
                 'temperature': 0, 'max_tokens': 8192, 'response_format': {'type': 'json_object'}},
    )
    try:
        raw = result.payload['choices'][0]['message']['content']
        if not isinstance(raw, str) or len(raw.encode('utf-8')) > 64000:
            raise ValueError('Invalid proposal response size')
        return validate_proposal(request, PlanProposal.model_validate_json(raw))
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        raise ServiceError('task_plan_invalid', '任务计划未通过校验，未开始业务执行。', 502) from exc
