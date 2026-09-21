"""Evidence gate for tax-related model conclusions."""

from __future__ import annotations

from .rule_registry import IssueCandidate

REQUIRED_TAX_FACTS = {
    "benchmark_taxpayer_status",
    "supplier_status",
    "quote_tax_basis",
    "quote_tax_rate",
    "input_tax_deductibility",
    "valuation_pricing_basis",
}


class TaxEvidencePolicy:
    def applies(self, candidate: IssueCandidate) -> bool:
        markers = ("税率", "纳税人", "进项税", "含税", "不含税")
        return candidate.category == "tax" or any(
            marker in candidate.description for marker in markers
        )

    def requires_verification(self, candidate: IssueCandidate) -> bool:
        if candidate.rule_id != "llm.review.v1" or not self.applies(candidate):
            return candidate.requires_verification
        supplied = {
            key
            for key, value in candidate.tax_evidence.items()
            if str(value).strip()
        }
        return (
            candidate.requires_verification
            or not REQUIRED_TAX_FACTS.issubset(supplied)
        )
