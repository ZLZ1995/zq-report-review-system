import pytest

from asset_based_agent.report_review_server.schemas import ReviewChunkRequest
from asset_based_agent.report_review_server.services.auth_service import ServiceError
from asset_based_agent.report_review_server.services.server_review_agent import (
    ServerReviewAgent,
)


def parse(description, paragraph=4):
    agent = ServerReviewAgent()
    batch = agent.build_batches([ReviewChunkRequest(
        chunk_id="c", source_file_id="f", source_file_name="report.docx",
        file_type="word", role="report", text="Visible evidence", location={"paragraph": 4},
    )])[0]
    return agent.parse_issues({"issues": [{
        "source_file_id": "f", "source_file_name": "report.docx",
        "category": "data_inconsistency", "risk_level": "low",
        "location": {"paragraph": paragraph}, "description": description,
        "evidence_summaries": ["Visible evidence"], "confidence": 0.6,
    }]}, batch=batch)[0]


def test_uncertainty_is_machine_readable():
    assert parse("【待核实】取值依据需要核查")["requires_verification"] is True


def test_definite_issue_does_not_become_pending():
    assert parse("【确定问题】公式与结果不一致")["requires_verification"] is False


def test_nonexistent_word_paragraph_is_rejected():
    with pytest.raises(ServiceError, match="位置"):
        parse("【确定问题】异常", paragraph=999)
