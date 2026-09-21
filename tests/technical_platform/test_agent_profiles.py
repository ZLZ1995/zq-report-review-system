"""G08：专用 Agent Profiles 与独立验证。

验收：简单任务不额外拆 Agent；复杂任务可控并行；故意制造的公式、版式、
哈希、模板和回执错误均由 Verifier 拦截；Verifier 只读不得改成果；
Browser Operator 绑定页面租约且不读凭据明文；Memory Curator 无业务文件写权限。
"""
import pytest
from pydantic import ValidationError


def test_all_eight_roles_present():
    from asset_based_agent.technical_platform.agent_profiles import PROFILES, AgentRole
    expected = {'conversation', 'intent_analyst', 'capability_router',
                'plan_compiler', 'domain_executor', 'independent_verifier',
                'memory_curator', 'browser_operator'}
    assert {profile.role for profile in PROFILES} == expected
    assert len(PROFILES) == 8
    for profile in PROFILES:
        assert profile.role in AgentRole.__args__


def test_profile_for_returns_frozen_record():
    from asset_based_agent.technical_platform.agent_profiles import profile_for
    profile = profile_for('domain_executor')
    assert profile.role == 'domain_executor'
    with pytest.raises(ValidationError):
        profile.token_budget = 1


def test_profile_for_unknown_role_rejected():
    from asset_based_agent.technical_platform.agent_profiles import profile_for
    with pytest.raises((KeyError, ValueError)):
        profile_for('ghost')


def test_every_profile_declares_full_contract():
    from asset_based_agent.technical_platform.agent_profiles import PROFILES
    for profile in PROFILES:
        assert profile.readable_context, profile.role
        assert profile.output_schema, profile.role
        assert profile.token_budget > 0, profile.role
        assert profile.model_policy in ('fast', 'standard', 'strong')


def test_verifier_is_read_only():
    from asset_based_agent.technical_platform.agent_profiles import profile_for
    verifier = profile_for('independent_verifier')
    assert 'artifact_write' in verifier.forbidden_data
    assert 'business_file_write' in verifier.forbidden_data
    assert not verifier.allowed_tools
    assert 'artifact' in verifier.readable_context
    assert 'evidence' in verifier.readable_context


def test_browser_operator_bound_to_lease_and_no_credentials():
    from asset_based_agent.technical_platform.agent_profiles import profile_for
    browser = profile_for('browser_operator')
    assert browser.requires_page_lease is True
    assert 'credential_plaintext' in browser.forbidden_data
    assert 'page_origin' in browser.readable_context


def test_memory_curator_cannot_write_business_files():
    from asset_based_agent.technical_platform.agent_profiles import profile_for
    curator = profile_for('memory_curator')
    assert 'business_file_write' in curator.forbidden_data


def test_plan_compiler_outputs_workflow_plan():
    from asset_based_agent.technical_platform.agent_profiles import profile_for
    assert profile_for('plan_compiler').output_schema == 'WorkflowPlan'


def test_allows_tool_enforcement():
    from asset_based_agent.technical_platform.agent_profiles import (
        allows_tool,
        profile_for,
    )
    executor = profile_for('domain_executor')
    assert allows_tool(executor, 'run_skill')
    assert not allows_tool(executor, 'browser_navigate')
    assert not allows_tool(profile_for('independent_verifier'), 'run_skill')


def test_allows_context_enforcement():
    from asset_based_agent.technical_platform.agent_profiles import (
        allows_context,
        profile_for,
    )
    conversation = profile_for('conversation')
    assert allows_context(conversation, 'conversation')
    verifier = profile_for('independent_verifier')
    assert not allows_context(verifier, 'credential_plaintext')
    assert not allows_context(verifier, 'memory_store')


def test_simple_task_does_not_split():
    from asset_based_agent.technical_platform.agent_profiles import should_split_agents
    decision = should_split_agents()
    assert decision.split is False
    assert decision.reasons == ()


def test_file_group_parallelism_splits():
    from asset_based_agent.technical_platform.agent_profiles import should_split_agents
    decision = should_split_agents(file_groups=3)
    assert decision.split is True
    assert 'file_group_parallel' in decision.reasons


def test_independent_verification_splits():
    from asset_based_agent.technical_platform.agent_profiles import should_split_agents
    decision = should_split_agents(needs_independent_verification=True)
    assert decision.split is True
    assert 'independent_verification' in decision.reasons


def test_multi_artifact_splits():
    from asset_based_agent.technical_platform.agent_profiles import should_split_agents
    decision = should_split_agents(artifact_count=2)
    assert decision.split is True
    assert 'multi_artifact' in decision.reasons


def test_context_overflow_splits():
    from asset_based_agent.technical_platform.agent_profiles import should_split_agents
    decision = should_split_agents(context_overflow=True)
    assert decision.split is True
    assert 'context_overflow' in decision.reasons


def make_claim(**overrides):
    from asset_based_agent.technical_platform.agent_profiles import ArtifactClaim
    base = {'artifact_id': 'a1', 'sha256': 'b' * 64, 'template_id': 'tpl-standard',
            'formulas': ('C2=SUM(D2:F2)',), 'layout': {'font': 'SimSun', 'size': '12'},
            'receipt': {'uploaded': 'yes', 'receipt_id': 'r1'}}
    base.update(overrides)
    return ArtifactClaim(**base)


def make_expected(**overrides):
    from asset_based_agent.technical_platform.agent_profiles import ExpectedArtifact
    base = {'sha256': 'b' * 64, 'template_id': 'tpl-standard',
            'formulas': ('C2=SUM(D2:F2)',), 'layout': {'font': 'SimSun', 'size': '12'},
            'receipt_fields': ('uploaded', 'receipt_id')}
    base.update(overrides)
    return ExpectedArtifact(**base)


def test_matching_artifact_passes_verification():
    from asset_based_agent.technical_platform.agent_profiles import verify_artifact
    report = verify_artifact(make_claim(), make_expected())
    assert report.passed is True
    assert report.failures == ()
    assert report.verifier_role == 'independent_verifier'


def test_hash_mismatch_intercepted():
    from asset_based_agent.technical_platform.agent_profiles import verify_artifact
    report = verify_artifact(make_claim(), make_expected(sha256='c' * 64))
    assert report.passed is False
    assert {f.kind for f in report.failures} == {'hash'}


def test_formula_mismatch_intercepted():
    from asset_based_agent.technical_platform.agent_profiles import verify_artifact
    report = verify_artifact(make_claim(formulas=('C2=D2+F2',)),
                             make_expected())
    assert report.passed is False
    assert 'formula' in {f.kind for f in report.failures}


def test_layout_mismatch_intercepted():
    from asset_based_agent.technical_platform.agent_profiles import verify_artifact
    report = verify_artifact(make_claim(layout={'font': 'Arial', 'size': '12'}),
                             make_expected())
    assert report.passed is False
    assert 'layout' in {f.kind for f in report.failures}


def test_template_mismatch_intercepted():
    from asset_based_agent.technical_platform.agent_profiles import verify_artifact
    report = verify_artifact(make_claim(template_id='tpl-other'),
                             make_expected())
    assert report.passed is False
    assert 'template' in {f.kind for f in report.failures}


def test_receipt_gap_intercepted():
    from asset_based_agent.technical_platform.agent_profiles import verify_artifact
    report = verify_artifact(make_claim(receipt={'uploaded': 'yes'}),
                             make_expected())
    assert report.passed is False
    assert 'receipt' in {f.kind for f in report.failures}


def test_multiple_failures_collected():
    from asset_based_agent.technical_platform.agent_profiles import verify_artifact
    report = verify_artifact(
        make_claim(sha256='d' * 64, template_id='tpl-x',
                   receipt={'uploaded': 'yes'}),
        make_expected())
    assert report.passed is False
    assert {'hash', 'template', 'receipt'} <= {f.kind for f in report.failures}


def test_unspecified_expectations_not_checked():
    from asset_based_agent.technical_platform.agent_profiles import (
        ExpectedArtifact,
        verify_artifact,
    )
    report = verify_artifact(make_claim(), ExpectedArtifact())
    assert report.passed is True
