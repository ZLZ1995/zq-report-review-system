"""G05：Skill Contract v2 与 12 项基础能力。

验收：每个正式 Skill 有正反例、输入角色和最小验收集；同 ID 冲突不静默覆盖；
锁定模板只能由可信官方版本更新；外部 ZIP 无法路径穿越/执行未知脚本
（由 skill_package 既有测试佐证）；基础能力为后台能力，不恢复手动切换。
"""
import pytest


def contract_kwargs(**overrides):
    kwargs = {
        'id': 'material-classifier', 'name': '资料分类', 'version': '1.0.0',
        'source': 'official_locked', 'trust_level': 'locked',
        'description': '把本轮资料分类为审核对象或参考',
        'when_to_use': '每轮执行前的资料归类', 'when_not_to_use': '纯问答',
        'positive_examples': ('把这几份资料分一下类',),
        'negative_examples': ('随便聊聊',),
        'input_roles': ('target', 'reference'),
        'required_inputs': ('target',), 'optional_inputs': ('reference',),
        'supported_extensions': ('.docx', '.xlsx'),
        'output_types': ('classification.json',),
        'allowed_tools': ('read_selected_files',),
        'network_policy': 'none', 'modifies_originals': False,
        'template_locks': (), 'resource_locks': (),
        'model_policy': 'optional', 'token_budget': 4000,
        'acceptance_gates': ('scope-consistency',),
        'feedback_schema': 'skill-feedback-v1',
        'compatibility': '>=1.0.0', 'migration': None,
    }
    kwargs.update(overrides)
    return kwargs


# --- 契约 schema ---

def test_contract_v2_builds_and_is_frozen():
    from asset_based_agent.technical_platform.skill_contract_v2 import SkillContractV2
    contract = SkillContractV2(**contract_kwargs())
    assert contract.id == 'material-classifier'
    with pytest.raises(ValueError):
        contract.name = '改'


def test_contract_v2_rejects_extra_fields():
    from asset_based_agent.technical_platform.skill_contract_v2 import SkillContractV2
    with pytest.raises(ValueError):
        SkillContractV2(**contract_kwargs(run_script='evil.py'))


def test_contract_v2_never_modifies_originals():
    from asset_based_agent.technical_platform.skill_contract_v2 import SkillContractV2
    with pytest.raises(ValueError):
        SkillContractV2(**contract_kwargs(modifies_originals=True))


def test_contract_v2_requires_examples_roles_and_gates():
    from asset_based_agent.technical_platform.skill_contract_v2 import SkillContractV2
    for field in ('positive_examples', 'negative_examples', 'input_roles',
                  'acceptance_gates'):
        with pytest.raises(ValueError):
            SkillContractV2(**contract_kwargs(**{field: ()}))


def test_contract_v2_version_is_semver():
    from asset_based_agent.technical_platform.skill_contract_v2 import SkillContractV2
    with pytest.raises(ValueError):
        SkillContractV2(**contract_kwargs(version='latest'))


def test_contract_v2_rejects_unknown_source_and_network_policy():
    from asset_based_agent.technical_platform.skill_contract_v2 import SkillContractV2
    with pytest.raises(ValueError):
        SkillContractV2(**contract_kwargs(source='random-dude'))
    with pytest.raises(ValueError):
        SkillContractV2(**contract_kwargs(network_policy='open'))


# --- 来源优先级与冲突 ---

def resolve(items):
    from asset_based_agent.technical_platform.skill_contract_v2 import resolve_conflicts
    return resolve_conflicts(items)


def test_higher_priority_source_wins_same_id():
    locked = contract_kwargs(source='official_locked', trust_level='locked')
    external = contract_kwargs(source='user_external', trust_level='low',
                               description='另一个描述')
    from asset_based_agent.technical_platform.skill_contract_v2 import SkillContractV2
    winners, report = resolve([SkillContractV2(**external), SkillContractV2(**locked)])
    assert winners['material-classifier'].source == 'official_locked'
    assert report.overridden == ('user_external',)


def test_same_priority_conflict_is_never_silent():
    from asset_based_agent.technical_platform.skill_contract_v2 import SkillContractV2
    first = SkillContractV2(**contract_kwargs(description='甲'))
    second = SkillContractV2(**contract_kwargs(description='乙'))
    with pytest.raises(ValueError):
        resolve([first, second])


def test_identical_duplicates_are_accepted():
    from asset_based_agent.technical_platform.skill_contract_v2 import SkillContractV2
    first = SkillContractV2(**contract_kwargs())
    second = SkillContractV2(**contract_kwargs())
    winners, report = resolve([first, second])
    assert winners['material-classifier'].version == '1.0.0'
    assert report.overridden == ()


def test_locked_template_only_updates_from_locked_source():
    from asset_based_agent.technical_platform.skill_contract_v2 import (
        SkillContractV2,
        assert_template_update_allowed,
    )
    locked = SkillContractV2(**contract_kwargs(template_locks=('template.xlsx',)))
    external = SkillContractV2(**contract_kwargs(source='user_external',
                                                 trust_level='low',
                                                 template_locks=('template.xlsx',)))
    with pytest.raises(PermissionError):
        assert_template_update_allowed(locked, external)
    official = SkillContractV2(**contract_kwargs(template_locks=('template.xlsx',),
                                                 version='1.1.0'))
    assert_template_update_allowed(locked, official)


# --- 12 项基础能力 ---

def test_foundation_capabilities_cover_required_set():
    from asset_based_agent.technical_platform.skill_contract_v2 import (
        foundation_capabilities,
    )
    expected = {'material-classifier', 'turn-scope-resolver', 'office-runtime-preflight',
                'document-evidence-indexer', 'spreadsheet-formula-auditor',
                'document-layout-verifier', 'artifact-integrity-verifier',
                'task-reconciliation', 'provider-diagnostics',
                'browser-receipt-verifier', 'memory-curator', 'skill-lint-and-eval'}
    capabilities = foundation_capabilities()
    assert {item.id for item in capabilities} == expected
    assert len(capabilities) == 12


def test_foundation_capabilities_are_complete_contracts():
    from asset_based_agent.technical_platform.skill_contract_v2 import (
        foundation_capabilities,
    )
    for capability in foundation_capabilities():
        assert capability.positive_examples and capability.negative_examples
        assert capability.input_roles and capability.acceptance_gates
        assert capability.modifies_originals is False
        assert capability.source == 'official_locked'
        assert capability.trust_level == 'locked'


def test_foundation_capabilities_are_deterministic():
    from asset_based_agent.technical_platform.skill_contract_v2 import (
        foundation_capabilities,
    )
    first = [item.model_dump_json() for item in foundation_capabilities()]
    second = [item.model_dump_json() for item in foundation_capabilities()]
    assert first == second


# --- 既有业务 Skill 路由兼容 ---

def test_business_skills_have_v2_descriptors():
    from asset_based_agent.technical_platform.skill_contract_v2 import (
        business_skill_descriptors,
    )
    descriptors = {item.id: item for item in business_skill_descriptors()}
    for expected in ('report.review', 'valuation-detail-workbook-fill',
                     'gongshang-change-history-docx', 'financial-brief-docx',
                     'office-workflow-to-skill'):
        assert expected in descriptors
        assert descriptors[expected].positive_examples
        assert descriptors[expected].negative_examples
