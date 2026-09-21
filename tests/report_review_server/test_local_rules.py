import json

from asset_based_agent.report_review_server.schemas import ReviewChunkRequest
from asset_based_agent.report_review_server.services.server_review_agent import (
    ServerReviewAgent,
)


def test_local_rules_included_in_payload_used_for_usage_estimate():
    agent = ServerReviewAgent()
    chunk = ReviewChunkRequest(chunk_id="c", source_file_id="f", source_file_name="a.docx",
                               file_type="word", role="report", text="visible text")
    plain = agent.build_batches([chunk])[0]
    local = agent.build_batches([chunk], "check asset scope " * 100)[0]
    request = agent.request_payload(local)
    assert "check asset scope" in request["messages"][1]["content"]
    assert len(json.dumps(request)) > len(json.dumps(agent.request_payload(plain)))
    assert request["response_format"] == {"type": "json_object"}
