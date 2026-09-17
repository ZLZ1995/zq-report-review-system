"""Metered structured understanding, separate from task execution and authorization."""
import json
from pathlib import Path

try:
    from ...agent_contracts import TaskUnderstanding, UnderstandingRequest, validate_understanding
except ModuleNotFoundError:  # pragma: no cover - legacy Zeabur build context
    from ..compat_agent_contracts import TaskUnderstanding, UnderstandingRequest, validate_understanding
from .auth_service import ServiceError
from .provider_gateway import NormalizedUsage


def understand_task(metered, db, user_id, request: UnderstandingRequest):
    instructions = Path(__file__).parents[1].joinpath('prompts/task_understanding.txt').read_text('utf-8')
    instructions += '\nJSON Schema:\n' + json.dumps(TaskUnderstanding.model_json_schema(), ensure_ascii=False)
    body = request.model_dump(exclude={'model_id', 'request_id'})
    content = json.dumps(body, ensure_ascii=False)
    result = metered.execute(
        db, user_id=user_id, model_id=request.model_id,
        client_request_id='understand:' + request.request_id,
        estimated_usage=NormalizedUsage(input_tokens=len(instructions) + len(content), output_tokens=4096),
        payload={'messages': [{'role': 'system', 'content': instructions},
                              {'role': 'user', 'content': content}],
                 'temperature': 0, 'max_tokens': 4096, 'response_format': {'type': 'json_object'}},
    )
    try:
        raw = result.payload['choices'][0]['message']['content']
        if not isinstance(raw, str) or len(raw.encode('utf-8')) > 64000:
            raise ValueError('Invalid understanding response size')
        return validate_understanding(request, TaskUnderstanding.model_validate_json(raw))
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        raise ServiceError('task_understanding_invalid',
                           '任务理解结果未通过校验，未开始执行，请补充本轮要求。', 502) from exc
