from __future__ import annotations

import pytest

from asset_based_agent.report_review_app.domain.enums import FileRole
from asset_based_agent.report_review_app.domain.models import IssueLocation
from asset_based_agent.report_review_app.services.document_extraction_service import (
    DocumentChunk,
)
from asset_based_agent.report_review_app.services.privacy_filter import ReviewBatch
from asset_based_agent.report_review_app.services.remote_auth_service import (
    InsufficientBalance,
    NetworkUnavailable,
)
from asset_based_agent.report_review_app.services.remote_review_llm import (
    RemoteReviewLlm,
)
from asset_based_agent.report_review_app.services.review_llm_client import (
    ReviewNetworkError,
    ReviewResponseSchemaError,
)


class FakeRemoteClient:
    def __init__(self) -> None:
        self.created_payload: dict[str, object] | None = None

    def get_balance(self) -> dict[str, str]:
        return {"balance": "12.34", "currency": "CNY"}

    def create_review_job(self, payload: dict[str, object]) -> dict[str, object]:
        self.created_payload = payload
        return {"job_id": "JOB-1", "status": "queued"}

    def execute_review_job(self, job_id: str) -> dict[str, object]:
        return {
            "job_id": job_id,
            "status": "succeeded",
            "issues": [
                {
                    "source_file_id": "FILE-1",
                    "source_file_name": "report.docx",
                    "category": "data_inconsistency",
                    "risk_level": "high",
                    "location": {"paragraph": 1},
                    "description": "A server-side issue",
                    "evidence_summaries": ["evidence"],
                    "recommendation": "check",
                    "confidence": 0.9,
                }
            ],
        }

    def get_review_job(self, job_id: str) -> dict[str, object]:
        return {
            "job_id": job_id,
            "status": "succeeded",
            "batch_count": 1,
            "completed_batches": 1,
        }


def _batch() -> ReviewBatch:
    return ReviewBatch(
        batch_id="BATCH-0001",
        character_count=12,
        chunks=[
            DocumentChunk(
                chunk_id="CHUNK-1",
                source_file_id="FILE-1",
                source_file_name="report.docx",
                role=FileRole.MAIN_REPORT,
                text="visible report text",
                location=IssueLocation(paragraph=1),
            )
        ],
    )


def test_updated_local_review_rules_are_sent_with_user_confirmations():
    from pathlib import Path
    rules = (Path(__file__).resolve().parents[2] /
             'src/asset_based_agent/technical_platform/review_rules.txt').read_text(encoding='utf-8')
    client = FakeRemoteClient()
    adapter = RemoteReviewLlm(client, model_id='MODEL-1', skill_instructions=rules,
                              user_request='报告日期已确认暂空，仅审核其余内容')
    adapter.review_batches([_batch()])
    assert client.created_payload['skill_instructions'] == rules
    assert client.created_payload['user_request'] == '报告日期已确认暂空，仅审核其余内容'


class TimeoutClient(FakeRemoteClient):
    def __init__(self):
        super().__init__()
        self.executions = 0
        self.polls = 0

    def execute_review_job(self, job_id):
        self.executions += 1
        raise NetworkUnavailable("timeout")

    def get_review_job(self, job_id):
        assert job_id == "JOB-1"
        self.polls += 1
        if self.polls == 1:
            return {"status": "running", "completed_batches": 1, "batch_count": 3}
        return super().execute_review_job(job_id)


def test_user_request_is_transmitted_separately_from_skill_rules():
    client = FakeRemoteClient()
    adapter = RemoteReviewLlm(
        client, model_id="MODEL-1", user_request="只检查金额", skill_instructions="只读审核"
    )
    adapter.review_batches([_batch()])
    assert client.created_payload["user_request"] == "只检查金额"
    assert client.created_payload["skill_instructions"] == "只读审核"


def test_execute_timeout_recovers_same_job_without_resubmitting():
    client = TimeoutClient()
    adapter = RemoteReviewLlm(client, model_id="MODEL-1", poll_interval=0.001)
    assert adapter.review_batches([_batch()])[0].source_file_id == "FILE-1"
    assert client.executions == 1
    assert client.polls >= 2


def test_async_execute_acceptance_is_polled_to_terminal_result():
    class AsyncAcceptedClient(FakeRemoteClient):
        def __init__(self):
            super().__init__()
            self.polls = 0

        def execute_review_job(self, job_id):
            return {"job_id": job_id, "status": "queued", "event_sequence": 2}

        def get_review_job(self, job_id):
            self.polls += 1
            if self.polls == 1:
                return {
                    "job_id": job_id,
                    "status": "running",
                    "completed_batches": 0,
                    "batch_count": 1,
                    "event_sequence": 3,
                }
            return FakeRemoteClient.execute_review_job(self, job_id)

    client = AsyncAcceptedClient()
    adapter = RemoteReviewLlm(client, model_id="MODEL-1", poll_interval=0.001)
    issues = adapter.review_batches([_batch()])
    assert issues[0].description == "A server-side issue"
    assert client.polls == 2


def test_polling_reports_actual_server_batch_progress():
    client = TimeoutClient()
    events = []
    adapter = RemoteReviewLlm(client, model_id="MODEL-1", poll_interval=0.001)
    adapter.review_batches([_batch()], events.append)
    assert any(
        e.get("completed_batches") == 1 and e["batch_total"] == 3 for e in events
    )
    assert events[-1]["state"] == "completed"


def test_lost_connection_is_pending_not_definitive_failure():
    class OfflineClient(TimeoutClient):
        def get_review_job(self, job_id):
            raise NetworkUnavailable("offline")

    client = OfflineClient()
    adapter = RemoteReviewLlm(
        client, model_id="MODEL-1", poll_interval=0.001, result_wait_seconds=0.02
    )
    with pytest.raises(ReviewNetworkError, match="状态尚未确认.*JOB-1"):
        adapter.review_batches([_batch()])
    assert client.executions == 1


def test_server_failure_after_timeout_is_reported():
    class FailedClient(TimeoutClient):
        def get_review_job(self, job_id):
            return {"status": "failed", "error_code": "provider_timeout"}

    adapter = RemoteReviewLlm(FailedClient(), model_id="MODEL-1", poll_interval=0.001)
    with pytest.raises(ReviewResponseSchemaError, match="provider_timeout"):
        adapter.review_batches([_batch()])


def test_stale_server_worker_is_classified_after_poll_deadline():
    class StaleClient(FakeRemoteClient):
        def execute_review_job(self, job_id):
            return {"status": "queued"}

        def get_review_job(self, job_id):
            return {
                "status": "running",
                "heartbeat_status": "stale",
                "completed_batches": 0,
                "batch_count": 1,
            }

    adapter = RemoteReviewLlm(
        StaleClient(),
        model_id="MODEL-1",
        poll_interval=0.001,
        result_wait_seconds=0.01,
    )
    with pytest.raises(ReviewNetworkError, match="心跳超时"):
        adapter.review_batches([_batch()])


def test_partial_issues_are_emitted_before_completion():
    class PartialClient(TimeoutClient):
        def get_review_job(self, job_id):
            self.polls += 1
            result = FakeRemoteClient.execute_review_job(self, job_id)
            if self.polls < 3:
                result["status"] = "running"
            return result

    events = []
    adapter = RemoteReviewLlm(PartialClient(), model_id="MODEL-1", poll_interval=0.001)
    adapter.review_batches([_batch()], events.append)
    outputs = [e for e in events if e.get("state") == "output"]
    assert len(outputs) == 1
    assert outputs[0]["issues"][0]["description"] == "A server-side issue"
    assert events.index(outputs[0]) < len(events) - 1


def test_remote_review_llm_uses_business_job_api_and_returns_issue_candidates() -> None:
    client = FakeRemoteClient()
    adapter = RemoteReviewLlm(client, model_id="MODEL-1", round_number=2)
    adapter.set_client_job_id("PROJECT-1-ROUND-2")
    progress: list[dict[str, object]] = []

    issues = adapter.review_batches([_batch()], progress_callback=progress.append)

    assert client.created_payload is not None
    assert client.created_payload["model_id"] == "MODEL-1"
    assert client.created_payload["round_number"] == 2
    assert client.created_payload["client_job_id"] == "PROJECT-1-ROUND-2"
    chunks = client.created_payload["chunks"]
    assert isinstance(chunks, list)
    assert "original_path" not in chunks[0]
    assert set(chunks[0]["location"]) == {
        "chapter",
        "page",
        "paragraph",
        "table",
        "cell",
    }
    assert issues[0].source_file_id == "FILE-1"
    assert progress[-1]["state"] == "completed"


def test_remote_review_llm_blocks_round_when_balance_is_zero() -> None:
    class EmptyBalanceClient(FakeRemoteClient):
        def get_balance(self) -> dict[str, str]:
            return {"balance": "0.00", "currency": "CNY"}

    adapter = RemoteReviewLlm(EmptyBalanceClient(), model_id="MODEL-1")

    try:
        adapter.review_batches([_batch()])
    except ReviewResponseSchemaError as exc:
        assert "余额不足" in str(exc)
    else:
        raise AssertionError("zero balance must block a review round")


def test_remote_review_llm_does_not_round_a_positive_balance_down_to_zero() -> None:
    class MicroscopicBalanceClient(FakeRemoteClient):
        def get_balance(self) -> dict[str, str]:
            return {"balance": "1E-1000", "currency": "CNY"}

    client = MicroscopicBalanceClient()
    adapter = RemoteReviewLlm(client, model_id="MODEL-1")

    adapter.review_batches([_batch()])

    assert client.created_payload is not None


def test_remote_review_llm_reports_server_hold_balance_rejection() -> None:
    class HoldRejectedClient(FakeRemoteClient):
        def create_review_job(self, payload: dict[str, object]) -> dict[str, object]:
            raise InsufficientBalance("余额不足，无法冻结本轮审核额度。")

    adapter = RemoteReviewLlm(HoldRejectedClient(), model_id="MODEL-1")

    try:
        adapter.review_batches([_batch()])
    except ReviewResponseSchemaError as exc:
        assert "余额不足" in str(exc)
        assert "会话" not in str(exc)
    else:
        raise AssertionError("server hold rejection must block the review round")
