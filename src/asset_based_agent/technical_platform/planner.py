"""Compile existing single-adapter tasks into explicit, version-bound plans.

Multi-step proposals use ExecutionPlan, but require the durable scheduler before
execution; this adapter does not silently flatten a compound task.
"""
from .execution_plan import ExecutionPlan, ExecutionStep
from .tool_contracts import skill_tool


def single_adapter_plan(identity, skill, files, rules_sha256):
    tool = skill_tool(skill.id)
    return ExecutionPlan(
        identity=identity, revision=1,
        input_versions={f['id']: f['sha256'] for f in files},
        steps=[ExecutionStep(identity=identity, step_id='execute', tool=tool.id,
                             tool_version=tool.version, skill_id=skill.id, skill_version=skill.version,
                             rules_sha256=rules_sha256, inputs=[f['id'] for f in files],
                             output_ref='task-result', acceptance_gates=list(tool.acceptance_gates))],
    )


def compile_proposal(request, understanding, proposal, identity, *, rules_hashes, revision):
    """Bind a model's proposal to current evidence and locally trusted adapters.

    Compilation is not authorization and does not call any business tool.
    A separate permission receipt must bind the complete compiled task snapshot.
    """
    from hashlib import sha256
    from pathlib import PurePath

    from ..agent_contracts import (
        PlanningRequest,
        PlanProposal,
        TaskUnderstanding,
        UnderstandingRequest,
        validate_proposal,
        validate_understanding,
    )
    from .execution_contracts import TaskIdentity
    from .skill_contracts import builtin_contracts
    from .skills import BUILTINS

    request = UnderstandingRequest.model_validate(request.model_dump())
    understanding = TaskUnderstanding.model_validate(understanding.model_dump())
    validate_understanding(request, understanding)
    identity = TaskIdentity.model_validate(identity.model_dump())
    proposal = PlanProposal.model_validate(proposal.model_dump() if isinstance(proposal, PlanProposal) else proposal)
    validate_proposal(PlanningRequest(request=request, understanding=understanding), proposal)
    if (understanding.next_action != 'plan' or proposal.request_id != request.request_id
            or identity.request_id != request.request_id):
        raise ValueError('Proposal does not match the active execution request')
    if {s.skill_id for s in proposal.steps} != set(understanding.skill_ids):
        raise ValueError('Proposal must cover exactly the understood skills')
    candidates = {s.id: s for s in request.skills}
    builtins = {s.id: s for s in BUILTINS}
    contracts = builtin_contracts()
    sources = {f.id: f for f in request.files}
    selected = set(understanding.targets + understanding.references)
    outputs = {s.step_id: 'step-result-' + sha256(s.step_id.encode()).hexdigest() for s in proposal.steps}
    producers = {s.step_id: s for s in proposal.steps}
    if len(outputs) != len(proposal.steps):
        raise ValueError('Duplicate proposed step')
    used, steps = set(), []
    for proposed in proposal.steps:
        candidate = candidates[proposed.skill_id]
        skill = builtins[candidate.adapter]
        tool = skill_tool(skill.id)
        inputs, targets, references = [], [], []
        for item in proposed.inputs:
            if item.kind == 'file':
                if (item.ref not in selected or
                        (item.role == 'target') != (item.ref in understanding.targets)):
                    raise ValueError('Proposed input or role differs from the understood scope')
                reference = item.ref
                used.add(reference)
                extension = PurePath(sources[reference].name).suffix.lower()
            else:
                if item.ref not in outputs:
                    raise ValueError('Unknown output producer')
                reference = outputs[item.ref]
                producer_skill = candidates[producers[item.ref].skill_id].adapter
                extension = {'history.generate': '.docx', 'detail.generate': '.xlsx',
                             'financial-brief.generate': '.docx',
                             'workflow-skill.validate': '.json'}.get(
                    skill_tool(producer_skill).id)
            if extension is None or extension not in contracts[skill.id].source_extensions:
                raise ValueError('Input type is not supported by the consuming skill')
            if skill.id == 'report.review' and extension == '.pdf' and item.role != 'reference':
                raise ValueError('PDF is reference-only')
            inputs.append(reference)
            (targets if item.role == 'target' else references).append(reference)
        if not proposed.goal.strip():
            raise ValueError('Step goal cannot be blank')
        if proposed.skill_id not in rules_hashes:
            raise ValueError('Trusted skill rules are missing')
        steps.append(ExecutionStep(
            identity=identity, step_id=proposed.step_id, tool=tool.id, tool_version=tool.version,
            skill_id=skill.id, skill_version=skill.version, rules_sha256=rules_hashes[proposed.skill_id],
            inputs=inputs, target_inputs=targets, reference_inputs=references,
            goal=proposed.goal, constraints=list(understanding.constraints),
            dependencies=proposed.dependencies, output_ref=outputs[proposed.step_id],
            acceptance_gates=list(tool.acceptance_gates)))
    if used != selected:
        raise ValueError('Proposal omitted selected files')
    return ExecutionPlan(identity=identity, revision=revision,
                         input_versions={ref: sources[ref].sha256 for ref in sorted(selected)}, steps=steps)
