import pytest

from asset_based_agent.agent_contracts import TaskUnderstanding, UnderstandingRequest


@pytest.mark.parametrize('skill,filename,action', [
    ('gongshang-change-history-docx', '变更.pdf', 'ask'),
    ('valuation-detail-workbook-fill', '报表.docx', 'ask'),
    ('report.review', '参考.pdf', 'ask'),
    ('review.preflight', '参考.pdf', 'plan'),
    ('valuation-detail-workbook-fill', '报表.xlsx', 'plan'),
])
def test_policy_checks_actual_adapter_input_before_business_execution(skill, filename, action):
    from asset_based_agent.technical_platform.understanding_policy import (
        assess_understanding,
    )
    request = UnderstandingRequest(request_id='r', model_id='m', message_id='msg', prompt='处理资料',
                                   files=[{'id': 'f', 'name': filename, 'sha256': 'a' * 64}],
                                   skills=[{'id': skill, 'adapter': skill, 'name': '能力', 'description': ''}])
    proposal = TaskUnderstanding(message_intent='execute', goal='处理资料', targets=['f'],
                                 references=[], excluded=[], constraints=[], deliverables=[],
                                 missing_inputs=[], evidence_message_ids=['msg'], skill_ids=[skill],
                                 next_action='plan', reply='准备处理资料。')
    result = assess_understanding(request, proposal)
    assert result.next_action == action
    if action == 'ask':
        assert result.skill_ids == []
        assert result.missing_inputs


@pytest.mark.parametrize('filename,expected', [('report.docx', 'plan'), ('program.exe', 'ask')])
def test_compound_understanding_does_not_assign_every_file_to_every_skill(filename, expected):
    from asset_based_agent.technical_platform.understanding_policy import (
        assess_understanding,
    )
    skills = ['gongshang-change-history-docx', 'report.review']
    request = UnderstandingRequest(request_id='r', model_id='m', message_id='msg', prompt='生成沿革并审核报告',
        files=[{'id': 'history', 'name': 'history.xlsx', 'sha256': 'a' * 64},
               {'id': 'report', 'name': filename, 'sha256': 'b' * 64}],
        skills=[{'id': s, 'adapter': s, 'name': s, 'description': ''} for s in skills])
    result = TaskUnderstanding(message_intent='execute', goal=request.prompt, targets=['history', 'report'],
        references=[], excluded=[], constraints=[], deliverables=[], missing_inputs=[],
        evidence_message_ids=['msg'], skill_ids=skills, next_action='plan', reply='准备分步骤执行')
    assert assess_understanding(request, result).next_action == expected
