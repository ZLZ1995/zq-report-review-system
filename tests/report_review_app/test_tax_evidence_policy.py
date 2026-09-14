from asset_based_agent.report_review_app.domain.enums import RiskLevel
from asset_based_agent.report_review_app.domain.models import IssueLocation
from asset_based_agent.report_review_app.services.rule_registry import IssueCandidate
from asset_based_agent.report_review_app.services.tax_evidence_policy import (
    REQUIRED_TAX_FACTS,
    TaxEvidencePolicy,
)


def candidate(tax_evidence: dict[str, str]) -> IssueCandidate:
    return IssueCandidate(
        source_file_id="FILE-1",
        source_file_name="说明.docx",
        category="tax",
        risk_level=RiskLevel.HIGH,
        location=IssueLocation(paragraph=1),
        description="不含税价格使用的税率错误。",
        confidence=0.9,
        rule_id="llm.review.v1",
        tax_evidence=tax_evidence,
    )


def test_tax_conclusion_requires_all_prerequisite_facts() -> None:
    assert TaxEvidencePolicy().requires_verification(
        candidate({"benchmark_taxpayer_status": "小规模纳税人"})
    )


def test_tax_conclusion_can_be_confirmed_when_all_facts_are_present() -> None:
    evidence = {key: "已核实" for key in REQUIRED_TAX_FACTS}

    assert not TaxEvidencePolicy().requires_verification(candidate(evidence))
