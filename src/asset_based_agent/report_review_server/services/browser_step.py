"""Metered next-action proposal. The server never operates client browsers."""
import json
from pathlib import Path

try:
    from ...browser_contracts import BrowserStepProposal, BrowserStepRequest, validate_browser_step
except ModuleNotFoundError:  # pragma: no cover - legacy Zeabur build context
    from ..compat_browser_contracts import BrowserStepProposal, BrowserStepRequest, validate_browser_step
from .auth_service import ServiceError
from .provider_gateway import NormalizedUsage


def propose_browser_step(metered, db, user_id, request: BrowserStepRequest):
    request = BrowserStepRequest.model_validate(request.model_dump())
    instructions = Path(__file__).parents[1].joinpath('prompts/browser_step.txt').read_text('utf-8')
    instructions += '\nJSON Schema:\n' + json.dumps(BrowserStepProposal.model_json_schema(), ensure_ascii=False)
    content = request.model_dump_json(exclude={'model_id'})
    result = metered.execute(db, user_id=user_id, model_id=request.model_id,
        client_request_id='browser:' + request.request_id,
        estimated_usage=NormalizedUsage(input_tokens=len(instructions)+len(content), output_tokens=4096),
        payload={'messages':[{'role':'system','content':instructions}, {'role':'user','content':content}],
                 'temperature':0, 'max_tokens':4096, 'response_format':{'type':'json_object'}})
    try:
        raw = result.payload['choices'][0]['message']['content']
        if not isinstance(raw, str) or len(raw.encode('utf-8')) > 32000:
            raise ValueError('Invalid browser proposal size')
        return validate_browser_step(request, BrowserStepProposal.model_validate_json(raw))
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        raise ServiceError('browser_step_invalid', '浏览器动作建议未通过校验，未执行网页操作。', 502) from exc
