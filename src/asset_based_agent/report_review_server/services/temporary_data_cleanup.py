"""Delete expired encrypted temporary review data while retaining audit metadata."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import BalanceHold, BillingRequest, ReviewJob, utc_now
from .auth_service import is_expired


def cleanup_expired_temporary_data(
    db: Session,
    *,
    now: datetime | None = None,
) -> dict[str, int]:
    cutoff = now or utc_now()
    counts = {
        "review_contexts": 0,
        "review_results": 0,
        "billing_results": 0,
        "expired_holds": 0,
    }
    jobs = list(
        db.scalars(
            select(ReviewJob).where(
                (ReviewJob.context_expires_at <= cutoff)
                | (ReviewJob.result_expires_at <= cutoff)
            )
        )
    )
    for job in jobs:
        if (
            job.context_ciphertext is not None
            and job.context_expires_at is not None
            and is_expired(job.context_expires_at, now=cutoff)
        ):
            job.context_ciphertext = None
            counts["review_contexts"] += 1
        if (
            job.result_ciphertext is not None
            and job.result_expires_at is not None
            and is_expired(job.result_expires_at, now=cutoff)
        ):
            job.result_ciphertext = None
            counts["review_results"] += 1
    billing_requests = list(
        db.scalars(
            select(BillingRequest).where(
                BillingRequest.response_ciphertext.is_not(None),
                BillingRequest.response_expires_at <= cutoff,
            )
        )
    )
    for request in billing_requests:
        request.response_ciphertext = None
        counts["billing_results"] += 1
    expired_holds = list(
        db.scalars(
            select(BalanceHold).where(
                BalanceHold.status == "active",
                BalanceHold.expires_at <= cutoff,
            )
        )
    )
    for hold in expired_holds:
        hold.status = "released"
        counts["expired_holds"] += 1
    db.commit()
    return counts
