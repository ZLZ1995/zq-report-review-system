from asset_based_agent.report_review_app.domain.enums import RiskLevel
from asset_based_agent.report_review_app.domain.models import IssueLocation
from asset_based_agent.report_review_app.services.issue_aggregation_service import (
    IssueAggregationService,
)
from asset_based_agent.report_review_app.services.rule_registry import IssueCandidate


def item(paragraph: int) -> IssueCandidate:
    return IssueCandidate(
        source_file_id="FILE-1",
        source_file_name="报告.docx",
        category="template_residue",
        risk_level=RiskLevel.HIGH,
        location=IssueLocation(paragraph=paragraph),
        description="报告编号存在未填写占位符。",
        confidence=1.0,
        rule_id="existing_adapter.template_placeholder.v1",
    )


def test_repeated_template_residue_is_merged_with_all_locations() -> None:
    results = IssueAggregationService().aggregate([item(1), item(20)])

    assert len(results) == 1
    assert [location.paragraph for location in results[0].occurrences] == [1, 20]
