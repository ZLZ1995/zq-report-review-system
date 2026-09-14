from __future__ import annotations

import json
from datetime import timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError
from sqlalchemy import select

from asset_based_agent.report_review_server.models import (
    BalanceHold,
    BillingRequest,
    ModelDefinition,
    ProviderRoute,
    ReviewJob,
    User,
    Wallet,
    WalletLedger,
    utc_now,
)
from asset_based_agent.report_review_server.schemas import (
    ReviewChunkRequest,
    ReviewJobCreateRequest,
)
from asset_based_agent.report_review_server.services.auth_service import ServiceError
from asset_based_agent.report_review_server.services.provider_gateway import (
    NormalizedUsage,
    ProviderCallError,
    ProviderResponse,
)
from asset_based_agent.report_review_server.services.review_job_service import (
    ReviewJobService,
)
from asset_based_agent.report_review_server.services.server_review_agent import (
    ServerReviewAgent,
)
from asset_based_agent.report_review_server.services.temporary_data_cleanup import (
    cleanup_expired_temporary_data,
)


class FakeProviderClient:
    def __init__(self, responses: list[object]) -> None:
        self.responses = list(responses)
        self.payloads: list[dict[str, object]] = []

    def call(self, route: ProviderRoute, payload: dict[str, object]) -> ProviderResponse:
        self.payloads.append(payload)
        outcome = self.responses.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        assert isinstance(outcome, dict)
        return ProviderResponse(
            payload=outcome,
            usage=NormalizedUsage(input_tokens=1_000, output_tokens=200),
        )


def test_user_request_reaches_every_model_batch():
    chunk = ReviewChunkRequest(
        chunk_id="C1", source_file_id="F1", source_file_name="a.docx",
        role="main_report", file_type="word", text="visible", location={"paragraph": 1},
    )
    request = ReviewJobCreateRequest(
        client_job_id="task", model_id="model", round_number=1,
        chunks=[chunk], user_request="只检查金额",
    )
    agent = ServerReviewAgent()
    batches = agent.build_batches(request.chunks, user_request=request.user_request)
    for batch in batches:
        prompt = agent.request_payload(batch)["messages"][-1]["content"]
        assert "只检查金额" in prompt
    assert ReviewJobCreateRequest(
        client_job_id="old", model_id="model", round_number=1, chunks=[chunk]
    ).user_request == ""


def _seed_review_case(client) -> tuple[str, str]:
    with client.app.state.session_factory() as db:
        user = User(
            username="review-user",
            display_name="Review User",
            password_hash="not-used",
            role="user",
            status="active",
            must_change_password=False,
        )
        model = ModelDefinition(
            code="review-model",
            display_name="Review Model",
            tier="standard",
            enabled=True,
            model_multiplier=Decimal("1.000000"),
            max_output_tokens=2_000,
        )
        db.add_all([user, model])
        db.flush()
        db.add(Wallet(user_id=user.user_id, balance=Decimal("100.00")))
        db.add(
            ProviderRoute(
                model_id=model.model_id,
                provider_type="deepseek",
                provider_model="deepseek-chat",
                base_url="https://api.deepseek.com",
                api_key_ciphertext="encrypted",
                priority=10,
                enabled=True,
                input_rate=Decimal("1.00000000"),
                output_rate=Decimal("2.00000000"),
                cache_hit_rate=Decimal("0.20000000"),
                cache_miss_rate=Decimal("1.00000000"),
                reasoning_rate=Decimal("2.00000000"),
            )
        )
        db.commit()
        return user.user_id, model.model_id


def _job_payload(model_id: str) -> ReviewJobCreateRequest:
    return ReviewJobCreateRequest(
        client_job_id="CLIENT-JOB-001",
        model_id=model_id,
        round_number=1,
        chunks=[
            ReviewChunkRequest(
                chunk_id="C-1",
                source_file_id="F-1",
                source_file_name="report.docx",
                file_type="word",
                role="report",
                text="A" * 7_000,
                location={"paragraph": 1},
            ),
            ReviewChunkRequest(
                chunk_id="C-2",
                source_file_id="F-2",
                source_file_name="detail.xlsx",
                file_type="excel",
                role="calculation_workbook",
                sheet_name="VisibleSheet",
                sheet_state="visible",
                text="B" * 7_000,
                location={"sheet": "VisibleSheet", "cell": "A1"},
            ),
        ],
    )


def _model_response(issue_number: int) -> dict[str, object]:
    content = json.dumps(
        {
            "issues": [
                {
                    "source_file_id": f"F-{issue_number}",
                    "source_file_name": "report.docx",
                    "category": "data_inconsistency",
                    "risk_level": "high",
                    "location": {"paragraph": issue_number},
                    "description": f"Issue {issue_number}",
                    "evidence_summaries": [f"Evidence {issue_number}"],
                    "recommendation": "Check source data",
                    "confidence": 0.9,
                }
            ]
        }
    )
    return {"choices": [{"message": {"content": content}}]}


def test_completed_batch_is_available_while_next_batch_runs(client):
    user_id, model_id = _seed_review_case(client)

    class CheckingProvider(FakeProviderClient):
        def call(self, route, payload):
            if self.payloads:
                with client.app.state.session_factory() as reader:
                    partial = service.get_job(reader, user_id=user_id, job_id=job.job_id)
                    assert partial.status == "running"
                    assert len(partial.issues) == 1
            return super().call(route, payload)

    provider = CheckingProvider([_model_response(1), _model_response(2)])
    service = ReviewJobService(client.app.state.settings, provider)
    with client.app.state.session_factory() as db:
        job = service.create_job(db, user_id=user_id, payload=_job_payload(model_id))
        service.execute_job(db, user_id=user_id, job_id=job.job_id)


def test_review_chunk_contract_rejects_hidden_sheet(client) -> None:
    _user_id, model_id = _seed_review_case(client)
    login_response = client.post(
        "/api/v1/auth/login",
        json={
            "username": "admin",
            "password": "AdminPassword123!",
            "client_instance_id": "hidden-test",
        },
    )
    token = login_response.json()["access_token"]
    response = client.post(
        "/api/v1/review-jobs",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "client_job_id": "HIDDEN-001",
            "model_id": model_id,
            "round_number": 1,
            "chunks": [
                {
                    "chunk_id": "C-HIDDEN",
                    "source_file_id": "F-HIDDEN",
                    "source_file_name": "detail.xlsx",
                    "file_type": "excel",
                    "role": "calculation_workbook",
                    "sheet_name": "HiddenSheet",
                    "sheet_state": "hidden",
                    "text": "must never reach the server",
                    "location": {"sheet": "HiddenSheet", "cell": "A1"},
                }
            ],
        },
    )

    assert response.status_code == 422
    assert b"must never reach the server" not in response.content


def test_review_contract_rejects_local_paths_and_extra_binary_fields() -> None:
    base = {
        "chunk_id": "C-1",
        "source_file_id": "F-1",
        "source_file_name": "C:\\private\\report.docx",
        "file_type": "word",
        "role": "report",
        "text": "visible text",
        "location": {"paragraph": 1},
    }
    with pytest.raises(ValidationError):
        ReviewChunkRequest.model_validate(base)

    base["source_file_name"] = "report.docx"
    base["original_path"] = "C:\\private\\report.docx"
    with pytest.raises(ValidationError):
        ReviewChunkRequest.model_validate(base)


def test_review_job_uses_one_round_hold_and_one_wallet_charge(client) -> None:
    user_id, model_id = _seed_review_case(client)
    provider = FakeProviderClient([_model_response(1), _model_response(2)])
    service = ReviewJobService(client.app.state.settings, provider)

    with client.app.state.session_factory() as db:
        job = service.create_job(db, user_id=user_id, payload=_job_payload(model_id))
        assert job.context_ciphertext is not None
        assert "report.docx" not in job.context_ciphertext
        assert job.batch_count == 2
        result = service.execute_job(db, user_id=user_id, job_id=job.job_id)
        holds = list(db.scalars(select(BalanceHold)))
        requests = list(db.scalars(select(BillingRequest)))
        charges = list(
            db.scalars(
                select(WalletLedger).where(WalletLedger.entry_type == "model_charge")
            )
        )

    assert result.status == "succeeded"
    assert result.completed_batches == 2
    assert len(result.issues) == 2
    assert len(provider.payloads) == 2
    assert len(holds) == 1
    assert holds[0].status == "captured"
    assert len(requests) == 2
    assert {request.hold_id for request in requests} == {holds[0].hold_id}
    assert len(charges) == 1


def test_review_job_creation_is_idempotent(client) -> None:
    user_id, model_id = _seed_review_case(client)
    service = ReviewJobService(client.app.state.settings, FakeProviderClient([]))

    with client.app.state.session_factory() as db:
        first = service.create_job(db, user_id=user_id, payload=_job_payload(model_id))
        second = service.create_job(db, user_id=user_id, payload=_job_payload(model_id))
        holds = list(db.scalars(select(BalanceHold)))

    assert first.job_id == second.job_id
    assert len(holds) == 1


def test_review_job_api_exposes_only_structured_job_result(client) -> None:
    _unused_user_id, model_id = _seed_review_case(client)
    with client.app.state.session_factory() as db:
        user = client.app.state.auth_service.create_user(
            db,
            username="api-review-user",
            display_name="API Review User",
            temporary_password="Temporary123",
        )
        client.app.state.wallet_service.adjust(
            db,
            user_id=user.user_id,
            amount=Decimal("100.00"),
            admin_user_id="test-admin",
        )
    provider = FakeProviderClient([_model_response(1), _model_response(2)])
    client.app.state.review_job_service = ReviewJobService(
        client.app.state.settings,
        provider,
    )
    login_response = client.post(
        "/api/v1/auth/login",
        json={
            "username": "api-review-user",
            "password": "Temporary123",
            "client_instance_id": "api-review-test",
        },
    )
    headers = {"Authorization": f"Bearer {login_response.json()['access_token']}"}

    created = client.post(
        "/api/v1/review-jobs",
        headers=headers,
        json=_job_payload(model_id).model_dump(mode="json"),
    )
    executed = client.post(
        f"/api/v1/review-jobs/{created.json()['job_id']}/execute",
        headers=headers,
    )

    assert created.status_code == 201
    assert executed.status_code == 200
    assert executed.json()["status"] == "succeeded"
    assert len(executed.json()["issues"]) == 2
    assert "context_ciphertext" not in executed.json()
    assert "charged_amount" not in executed.json()


def test_failed_review_captures_reported_usage_once(client) -> None:
    user_id, model_id = _seed_review_case(client)
    provider = FakeProviderClient(
        [
            ProviderCallError(
                "provider_timeout",
                "timeout",
                retryable=True,
                usage=NormalizedUsage(input_tokens=1_000),
            )
        ]
    )
    service = ReviewJobService(client.app.state.settings, provider)

    with client.app.state.session_factory() as db:
        job = service.create_job(db, user_id=user_id, payload=_job_payload(model_id))
        with pytest.raises(ServiceError):
            service.execute_job(db, user_id=user_id, job_id=job.job_id)
        db.expire_all()
        retained = db.get(ReviewJob, job.job_id)
        hold = db.get(BalanceHold, job.hold_id)
        charges = list(
            db.scalars(
                select(WalletLedger).where(WalletLedger.entry_type == "model_charge")
            )
        )

    assert retained is not None and retained.status == "failed"
    assert hold is not None and hold.status == "captured"
    assert len(charges) == 1


def test_model_cannot_create_issue_for_hidden_or_unknown_sheet(client) -> None:
    _user_id, model_id = _seed_review_case(client)
    agent = ServerReviewAgent()
    batches = agent.build_batches(_job_payload(model_id).chunks)
    hidden_sheet_response = {
        "issues": [
            {
                "source_file_id": "F-2",
                "source_file_name": "detail.xlsx",
                "category": "formula_error",
                "risk_level": "high",
                "location": {"sheet": "HiddenSheet", "cell": "A1"},
                "description": "Invented hidden-sheet issue",
                "evidence_summaries": ["Invented evidence"],
                "recommendation": "Check it",
                "confidence": 0.9,
            }
        ]
    }

    with pytest.raises(ServiceError) as exc_info:
        agent.parse_issues(hidden_sheet_response, batch=batches[1])

    assert exc_info.value.code == "review_response_invalid"


def test_expired_review_ciphertext_is_deleted_but_job_metadata_remains(client) -> None:
    user_id, model_id = _seed_review_case(client)
    provider = FakeProviderClient([_model_response(1), _model_response(2)])
    service = ReviewJobService(client.app.state.settings, provider)

    with client.app.state.session_factory() as db:
        job = service.create_job(db, user_id=user_id, payload=_job_payload(model_id))
        service.execute_job(db, user_id=user_id, job_id=job.job_id)
        job = db.get(ReviewJob, job.job_id)
        assert job is not None
        job.context_expires_at = utc_now() - timedelta(seconds=1)
        job.result_expires_at = utc_now() - timedelta(seconds=1)
        for request in db.scalars(select(BillingRequest)):
            request.response_expires_at = utc_now() - timedelta(seconds=1)
        db.commit()

        deleted = cleanup_expired_temporary_data(db, now=utc_now())
        db.expire_all()
        retained = db.get(ReviewJob, job.job_id)
        billing_requests = list(db.scalars(select(BillingRequest)))

    assert deleted == {
        "review_contexts": 1,
        "review_results": 1,
        "billing_results": 2,
        "expired_holds": 0,
    }
    assert retained is not None
    assert retained.status == "succeeded"
    assert retained.context_ciphertext is None
    assert retained.result_ciphertext is None
    assert all(request.response_ciphertext is None for request in billing_requests)


def test_cleanup_releases_expired_round_hold(client) -> None:
    user_id, model_id = _seed_review_case(client)
    service = ReviewJobService(client.app.state.settings, FakeProviderClient([]))

    with client.app.state.session_factory() as db:
        job = service.create_job(db, user_id=user_id, payload=_job_payload(model_id))
        hold = db.get(BalanceHold, job.hold_id)
        assert hold is not None
        hold.expires_at = utc_now() - timedelta(seconds=1)
        db.commit()

        deleted = cleanup_expired_temporary_data(db, now=utc_now())
        db.expire_all()
        retained = db.get(BalanceHold, job.hold_id)

    assert deleted["expired_holds"] == 1
    assert retained is not None and retained.status == "released"
