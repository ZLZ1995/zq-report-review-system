"""G06：声明式 WorkflowPlan 和本地可信编译器。

验收：恶意/错误计划均被本地拒绝；模型文本不能变成任意代码；同一输入编译
结果稳定；计划修订保留 revision 和差异原因；旧 planner 输出经兼容层等价。
"""
import pytest

NODE_TYPES = ('understand', 'classify_materials', 'extract_evidence', 'model_call',
              'run_skill', 'browser_action', 'validate_artifact',
              'verify_business_result', 'ask_user', 'deliver')


def make_envelope():
    from asset_based_agent.technical_platform.turn_scope_policy import resolve_scope
    files = [{'id': 'f1', 'name': '审核报告.docx', 'sha256': 'a' * 64},
             {'id': 'f2', 'name': '明细表.xlsx', 'sha256': 'b' * 64}]
    return resolve_scope(
        owner='alice', project_id='p1', session_id='s1',
        raw_user_text='审审核报告.docx，参考明细表.xlsx', selected_ids=['f1', 'f2'],
        available_files=files, active_model_id='model-a', permission_mode='risk',
        clock=None)


def node(node_id, node_type, inputs=(), depends_on=(), **config):
    return {'node_id': node_id, 'type': node_type, 'inputs': list(inputs),
            'depends_on': list(depends_on), 'config': config}


def attachment_input(file_id):
    return {'kind': 'attachment', 'ref': file_id}


def output_input(node_id):
    return {'kind': 'node_output', 'ref': node_id}


def valid_plan(envelope=None, **overrides):
    envelope = envelope or make_envelope()
    from asset_based_agent.technical_platform.turn_context import envelope_hash
    plan = {
        'plan_id': 'plan-1', 'revision': 1, 'envelope_hash': envelope_hash(envelope),
        'revision_reason': 'initial',
        'nodes': [
            node('u1', 'understand'),
            node('s1', 'run_skill', [attachment_input('f1'), attachment_input('f2')],
                 ['u1'], skill_id='report.review'),
            node('v1', 'validate_artifact', [output_input('s1')], ['s1']),
            node('d1', 'deliver', [output_input('v1')], ['v1']),
        ],
    }
    plan.update(overrides)
    return plan


def compile_valid(envelope=None, **plan_overrides):
    from asset_based_agent.technical_platform.workflow_compiler import compile_plan
    envelope = envelope or make_envelope()
    return compile_plan(valid_plan(envelope, **plan_overrides), envelope=envelope,
                        allowed_tools=('report.review', 'financial-brief-docx'))


# --- schema ---

def test_plan_builds_and_is_frozen():
    from asset_based_agent.technical_platform.workflow_plan import WorkflowPlan
    plan = WorkflowPlan.model_validate(valid_plan())
    with pytest.raises(ValueError):
        plan.revision = 2


def test_plan_rejects_unknown_node_type():
    from asset_based_agent.technical_platform.workflow_plan import WorkflowPlan
    with pytest.raises(ValueError):
        WorkflowPlan.model_validate(valid_plan(
            nodes=[node('x1', 'execute_shell')]))


def test_plan_rejects_duplicate_node_ids():
    from asset_based_agent.technical_platform.workflow_plan import WorkflowPlan
    with pytest.raises(ValueError):
        WorkflowPlan.model_validate(valid_plan(
            nodes=[node('a', 'understand'), node('a', 'deliver')]))


def test_plan_rejects_dependency_cycle():
    from asset_based_agent.technical_platform.workflow_plan import WorkflowPlan
    with pytest.raises(ValueError):
        WorkflowPlan.model_validate(valid_plan(nodes=[
            node('a', 'understand', depends_on=['c']),
            node('b', 'model_call', depends_on=['a']),
            node('c', 'deliver', depends_on=['b'])]))


def test_plan_rejects_unknown_dependency():
    from asset_based_agent.technical_platform.workflow_plan import WorkflowPlan
    with pytest.raises(ValueError):
        WorkflowPlan.model_validate(valid_plan(nodes=[
            node('a', 'understand', depends_on=['ghost']),
            node('d', 'deliver', [output_input('a')], ['a'])]))


def test_plan_rejects_orphan_deliver():
    from asset_based_agent.technical_platform.workflow_plan import WorkflowPlan
    with pytest.raises(ValueError):
        WorkflowPlan.model_validate(valid_plan(nodes=[
            node('u1', 'understand'),
            node('d1', 'deliver')]))


def test_plan_requires_deliver_sink():
    from asset_based_agent.technical_platform.workflow_plan import WorkflowPlan
    with pytest.raises(ValueError):
        WorkflowPlan.model_validate(valid_plan(nodes=[node('u1', 'understand')]))


def test_plan_rejects_extra_config_field_on_input():
    from asset_based_agent.technical_platform.workflow_plan import WorkflowPlan
    bad = valid_plan()
    bad['nodes'][1]['inputs'][0]['code'] = 'print(1)'
    with pytest.raises(ValueError):
        WorkflowPlan.model_validate(bad)


# --- 编译器 ---

def test_compile_valid_plan_produces_dag():
    compiled = compile_valid()
    assert compiled.envelope_hash
    assert [step.node_id for step in compiled.steps] == ['u1', 's1', 'v1', 'd1']


def test_compile_is_deterministic():
    envelope = make_envelope()
    assert compile_valid(envelope).compile_hash == compile_valid(envelope).compile_hash


def test_compile_rejects_unselected_attachment():
    with pytest.raises(ValueError):
        compile_valid(nodes=[
            node('u1', 'understand'),
            node('s1', 'run_skill', [attachment_input('f99')], ['u1'],
                 skill_id='report.review'),
            node('d1', 'deliver', [output_input('s1')], ['s1'])])


def test_compile_rejects_unknown_tool():
    with pytest.raises(ValueError):
        compile_valid(nodes=[
            node('u1', 'understand'),
            node('s1', 'run_skill', [attachment_input('f1')], ['u1'],
                 skill_id='shell.exec'),
            node('d1', 'deliver', [output_input('s1')], ['s1'])])


def test_compile_rejects_original_write():
    with pytest.raises(ValueError):
        compile_valid(nodes=[
            node('u1', 'understand'),
            node('s1', 'run_skill', [attachment_input('f1')], ['u1'],
                 skill_id='report.review', write_target='original'),
            node('d1', 'deliver', [output_input('s1')], ['s1'])])


def test_compile_rejects_cross_project_path():
    with pytest.raises(ValueError):
        compile_valid(nodes=[
            node('u1', 'understand'),
            node('s1', 'run_skill', [{'kind': 'literal',
                                      'ref': 'D:/其他项目/数据.xlsx'}], ['u1'],
                 skill_id='report.review'),
            node('d1', 'deliver', [output_input('s1')], ['s1'])])


def test_compile_rejects_budget_overflow():
    with pytest.raises(ValueError):
        compile_valid(nodes=[
            node('u1', 'understand'),
            node('s1', 'run_skill', [attachment_input('f1')], ['u1'],
                 skill_id='report.review', token_budget=10 ** 9),
            node('d1', 'deliver', [output_input('s1')], ['s1'])])


def test_compile_rejects_envelope_mismatch():
    from asset_based_agent.technical_platform.turn_scope_policy import resolve_scope
    from asset_based_agent.technical_platform.workflow_compiler import compile_plan
    other = resolve_scope(
        owner='alice', project_id='p1', session_id='s1',
        raw_user_text='审审核报告.docx', selected_ids=['f1'],
        available_files=[{'id': 'f1', 'name': '审核报告.docx', 'sha256': 'a' * 64}],
        active_model_id='model-a', permission_mode='risk', clock=None)
    with pytest.raises(ValueError):
        compile_plan(valid_plan(), envelope=other,
                     allowed_tools=('report.review',))


def test_revision_bump_keeps_reason():
    from asset_based_agent.technical_platform.workflow_plan import (
        WorkflowPlan,
        revise_plan,
    )
    plan = WorkflowPlan.model_validate(valid_plan())
    revised = revise_plan(plan, reason='用户调整了范围')
    assert revised.revision == 2
    assert revised.revision_reason == '用户调整了范围'
    assert revised.plan_id == plan.plan_id


# --- 旧 planner 兼容层 ---

def test_legacy_execution_plan_converts_to_workflow():
    from asset_based_agent.technical_platform.execution_contracts import TaskIdentity
    from asset_based_agent.technical_platform.planner import single_adapter_plan
    from asset_based_agent.technical_platform.skills import BUILTINS
    from asset_based_agent.technical_platform.workflow_compiler import (
        from_execution_plan,
    )
    skill = next(item for item in BUILTINS if item.id == 'report.review')
    identity = TaskIdentity(request_id='r1', owner='alice', project_id='p1',
                            session_id='s1', task_id='t1')
    legacy = single_adapter_plan(identity, skill,
                                 [{'id': 'f1', 'sha256': 'a' * 64}], 'c' * 64)
    envelope = make_envelope()
    workflow = from_execution_plan(legacy, envelope=envelope)
    types = [item.type for item in workflow.nodes]
    assert 'run_skill' in types and 'validate_artifact' in types
    assert types[-1] == 'deliver'
