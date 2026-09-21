import pytest


def identity():
    return {'owner': 'alice', 'project_id': 'p', 'session_id': 's', 'task_id': 't', 'request_id': 'r'}


def plan_data():
    return {'identity': identity(), 'revision': 1, 'input_versions': {'f': 'a' * 64},
            'steps': [{'identity': identity(), 'step_id': 'one', 'tool': 'preflight.execute',
                       'tool_version': 1, 'skill_id': 'review.preflight', 'skill_version': '0.1.0',
                       'rules_sha256': 'b' * 64, 'inputs': ['f'], 'output_ref': 'result-one',
                       'dependencies': [], 'acceptance_gates': ['visible_content_only', 'original_hash_unchanged']}]}


def test_plan_roundtrip_and_ready_order():
    from asset_based_agent.technical_platform.execution_plan import ExecutionPlan
    plan = ExecutionPlan.model_validate(plan_data())
    assert plan.ready_steps(set()) == ['one']
    assert plan.ready_steps({'one'}) == []
    assert ExecutionPlan.model_validate_json(plan.model_dump_json()) == plan


@pytest.mark.parametrize('change', [
    lambda p: p['steps'][0].update(tool='shell'),
    lambda p: p['steps'][0].update(inputs=['outside']),
    lambda p: p['steps'][0]['identity'].update(session_id='other'),
    lambda p: p['steps'][0].update(dependencies=['missing']),
    lambda p: p['steps'][0].update(tool_version=2),
    lambda p: p['steps'][0].update(skill_id='report.review'),
])
def test_plan_rejects_unknown_tool_input_scope_dependency_or_version(change):
    from asset_based_agent.technical_platform.execution_plan import ExecutionPlan
    value = plan_data()
    change(value)
    with pytest.raises(ValueError):
        ExecutionPlan.model_validate(value)


def test_plan_rejects_dependency_cycle():
    from asset_based_agent.technical_platform.execution_plan import ExecutionPlan
    value = plan_data()
    first = value['steps'][0]
    second = {**first, 'step_id': 'two', 'output_ref': 'result-two', 'dependencies': ['one']}
    first['dependencies'] = ['two']
    value['steps'].append(second)
    with pytest.raises(ValueError):
        ExecutionPlan.model_validate(value)


def test_plan_orders_dependency_outputs_and_rejects_unlinked_output_input():
    from asset_based_agent.technical_platform.execution_plan import ExecutionPlan
    value = plan_data()
    second = {**value['steps'][0], 'step_id': 'two', 'output_ref': 'result-two',
              'dependencies': ['one'], 'inputs': ['result-one']}
    value['steps'].append(second)
    plan = ExecutionPlan.model_validate(value)
    assert plan.ready_steps(set()) == ['one']
    assert plan.ready_steps({'one'}) == ['two']
    second['dependencies'] = []
    with pytest.raises(ValueError):
        ExecutionPlan.model_validate(value)
