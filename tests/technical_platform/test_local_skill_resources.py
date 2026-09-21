from pathlib import Path


def test_new_builtin_skill_resources_and_locked_template_are_present():
    from asset_based_agent.technical_platform.generation import bundle_directory
    from asset_based_agent.technical_platform.skills import (
        FINANCIAL_BRIEF,
        WORKFLOW_TO_SKILL,
    )

    financial = bundle_directory(FINANCIAL_BRIEF.id)
    workflow = bundle_directory(WORKFLOW_TO_SKILL.id)
    assert (financial / 'SKILL.md').is_file()
    assert (financial / 'scripts/run_brief.py').is_file()
    assert (financial / 'assets/financial_table.docx').is_file()
    assert (workflow / 'SKILL.md').is_file()
    assert (workflow / 'scripts/validate_workflow_contract.py').is_file()


def test_build_script_packages_all_reviewed_builtin_skills():
    root = Path(__file__).resolve().parents[2]
    text = (root / 'scripts/build_technical_platform.py').read_text(encoding='utf-8')
    for identity in ('valuation-detail-workbook-fill', 'gongshang-change-history-docx',
                     'financial-brief-docx', 'office-workflow-to-skill'):
        assert identity in text
