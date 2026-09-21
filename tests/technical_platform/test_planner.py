import pytest

from asset_based_agent.agent_contracts import TaskUnderstanding, UnderstandingRequest
from asset_based_agent.technical_platform.execution_contracts import TaskIdentity


def context():
    request = UnderstandingRequest(
        request_id='r', model_id='model', message_id='m', prompt='生成后只审核新文件',
        files=[{'id': 'source', 'name': 'source.xlsx', 'sha256': 'a' * 64}],
        skills=[{'id': 'gongshang-change-history-docx', 'name': 'history',
                 'adapter': 'gongshang-change-history-docx', 'description': ''},
                {'id': 'report.review', 'name': 'review', 'adapter': 'report.review', 'description': ''}])
    understanding = TaskUnderstanding(
        message_intent='execute', goal=request.prompt, targets=['source'], references=[], excluded=[],
        constraints=['原件不修改'], deliverables=['Word和审核意见'], missing_inputs=[],
        evidence_message_ids=['m'], skill_ids=[s.id for s in request.skills], next_action='plan', reply='生成后审核')
    proposal = {'request_id': 'r', 'steps': [
        {'step_id': 'generate', 'skill_id': 'gongshang-change-history-docx', 'goal': '生成历史沿革',
         'inputs': [{'kind': 'file', 'ref': 'source', 'role': 'target'}], 'dependencies': []},
        {'step_id': 'review', 'skill_id': 'report.review', 'goal': '仅审核生成的Word',
         'inputs': [{'kind': 'step_output', 'ref': 'generate', 'role': 'target'}],
         'dependencies': ['generate']} ]}
    identity = TaskIdentity(owner='alice', project_id='p', session_id='s', task_id='t', request_id='r')
    return request, understanding, proposal, identity


def compile_value(request, understanding, proposal, identity):
    from asset_based_agent.technical_platform.planner import compile_proposal
    return compile_proposal(request, understanding, proposal, identity,
                            rules_hashes={s.id: 'b' * 64 for s in request.skills}, revision=2)


def test_compiler_preserves_scope_goal_constraints_and_generated_reference():
    request, understanding, proposal, identity = context()
    plan = compile_value(request, understanding, proposal, identity)
    assert plan.revision == 2
    assert plan.input_versions == {'source': 'a' * 64}
    assert plan.steps[0].tool == 'history.generate'
    assert plan.steps[1].tool == 'review.execute'
    assert plan.steps[1].inputs == [plan.steps[0].output_ref]
    assert plan.steps[1].target_inputs == plan.steps[1].inputs
    assert plan.steps[1].reference_inputs == []
    assert plan.steps[1].goal == '仅审核生成的Word'
    assert plan.steps[1].constraints == ['原件不修改']
    assert plan.ready_steps(set()) == ['generate']


@pytest.mark.parametrize('mutation', [
    lambda p: p.update(request_id='stale'),
    lambda p: p['steps'][0].update(skill_id='unknown'),
    lambda p: p['steps'][0].update(tool='shell'),
    lambda p: p['steps'][0]['inputs'][0].update(ref='history-file'),
    lambda p: p['steps'][0]['inputs'][0].update(role='reference'),
    lambda p: p['steps'][1].update(dependencies=[]),
    lambda p: p['steps'][1]['inputs'][0].update(ref='review'),
    lambda p: p['steps'].pop(),
])
def test_compiler_rejects_unbound_or_incomplete_proposal(mutation):
    request, understanding, proposal, identity = context()
    mutation(proposal)
    with pytest.raises(ValueError):
        compile_value(request, understanding, proposal, identity)


def test_compiler_keeps_reference_files_distinct_from_targets():
    request, understanding, proposal, identity = context()
    request = request.model_copy(update={'files': [*request.files, request.files[0].model_copy(
        update={'id': 'reference', 'name': 'reference.docx'})]})
    understanding = understanding.model_copy(update={'references': ['reference']})
    proposal['steps'][1]['inputs'].append({'kind': 'file', 'ref': 'reference', 'role': 'reference'})
    plan = compile_value(request, understanding, proposal, identity)
    assert plan.steps[1].reference_inputs == ['reference']
    assert 'reference' not in plan.steps[1].target_inputs


def test_compiler_rejects_excluded_or_unused_selected_files():
    request, understanding, proposal, identity = context()
    request = request.model_copy(update={'files': [*request.files, request.files[0].model_copy(
        update={'id': 'old', 'name': 'old.xlsx'})]})
    excluded = understanding.model_copy(update={'excluded': ['old']})
    assert compile_value(request, excluded, proposal, identity).input_versions == {'source': 'a' * 64}
    unused = understanding.model_copy(update={'targets': ['source', 'old']})
    with pytest.raises(ValueError):
        compile_value(request, unused, proposal, identity)


def test_compiler_rejects_unsupported_source_format():
    request, understanding, proposal, identity = context()
    request = request.model_copy(update={'files': [request.files[0].model_copy(update={'name': 'source.pdf'})]})
    with pytest.raises(ValueError):
        compile_value(request, understanding, proposal, identity)


def test_compiler_rejects_review_issues_as_document_input():
    request, understanding, proposal, identity = context()
    proposal['steps'][0]['skill_id'] = 'report.review'
    proposal['steps'][1]['skill_id'] = 'gongshang-change-history-docx'
    with pytest.raises(ValueError):
        compile_value(request, understanding, proposal, identity)


@pytest.mark.parametrize('adapter', ['review.preflight', 'report.review'])
def test_pdf_can_be_preflight_target_but_not_review_target(adapter):
    request, understanding, proposal, identity = context()
    request = request.model_copy(update={
        'files': [request.files[0].model_copy(update={'name': 'source.pdf'})],
        'skills': [request.skills[1].model_copy(update={'id': adapter, 'adapter': adapter})],
    })
    understanding = understanding.model_copy(update={'skill_ids': [adapter]})
    proposal['steps'] = [dict(proposal['steps'][0], skill_id=adapter)]
    if adapter == 'report.review':
        with pytest.raises(ValueError, match='PDF is reference-only'):
            compile_value(request, understanding, proposal, identity)
    else:
        plan = compile_value(request, understanding, proposal, identity)
        assert plan.steps[0].target_inputs == ['source']
