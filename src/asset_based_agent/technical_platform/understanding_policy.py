"""Local capability guards; format compatibility is not evidence sufficiency."""
from pathlib import PurePath

from ..agent_contracts import TaskUnderstanding, validate_understanding
from .skill_contracts import builtin_contracts


def assess_understanding(request, result):
    validate_understanding(request, result)
    if result.next_action != 'plan':
        return result
    contracts = builtin_contracts()
    catalog = {s.id: s for s in request.skills}
    files = {f.id: f for f in request.files}
    problems = []
    if len(result.skill_ids) > 1:
        # Before a proposal exists there is no step/file assignment. Require each
        # target to fit at least one selected capability; the compiler later
        # checks every actual step input, including generated artifacts.
        adapters = [catalog[s].adapter for s in result.skill_ids]
        for identity in result.targets:
            suffix = PurePath(files[identity].name).suffix.lower()
            if not any(suffix in contracts[a].source_extensions
                       and not (a == 'report.review' and suffix == '.pdf') for a in adapters):
                problems.append('本轮目标包含所选能力均不支持的文件格式，请调整资料范围。')
        if not problems:
            return result
    for skill_id in result.skill_ids:
        if len(result.skill_ids) > 1:
            break
        adapter = catalog[skill_id].adapter
        contract = contracts[adapter]
        for identity in result.targets:
            suffix = PurePath(files[identity].name).suffix.lower()
            if adapter == 'report.review' and suffix == '.pdf':
                problems.append('PDF只能作为审核参考，请指定需审核的Word或Excel目标。')
            elif suffix not in contract.source_extensions:
                problems.append(f'{catalog[skill_id].name}当前软件适配器的目标格式为'
                                f'{"、".join(contract.source_extensions)}，请补充对应资料或调整任务。')
    if not problems:
        return result
    reply = '\n'.join(dict.fromkeys(problems))[:1000]
    return TaskUnderstanding.model_validate({
        **result.model_dump(), 'next_action': 'ask', 'skill_ids': [], 'reply': reply,
        'missing_inputs': [{'field': 'targets', 'question': reply}],
    })
