"""Persistent authentication models for the control plane."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "report_review_users"

    user_id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(128))
    email: Mapped[str | None] = mapped_column(String(320), unique=True, nullable=True)
    password_hash: Mapped[str] = mapped_column(Text)
    role: Mapped[str] = mapped_column(String(16), default="user")
    status: Mapped[str] = mapped_column(String(16), default="active")
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=True)
    registration_source: Mapped[str] = mapped_column(String(16), default="admin")
    billing_multiplier: Mapped[Decimal] = mapped_column(Numeric(12, 6), default=Decimal("1.000000"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )

    sessions: Mapped[list[AuthSession]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class ClientRelease(Base):
    """Immutable signed client manifest with an auditable lifecycle."""

    __tablename__ = "report_review_client_releases"
    __table_args__ = (UniqueConstraint("version", "platform", "arch", name="uq_client_release_target"),)

    release_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    version: Mapped[str] = mapped_column(String(32), index=True)
    platform: Mapped[str] = mapped_column(String(32))
    arch: Mapped[str] = mapped_column(String(32))
    sequence: Mapped[int] = mapped_column(Integer, unique=True)
    status: Mapped[str] = mapped_column(String(16), default="draft", index=True)
    manifest_json: Mapped[str] = mapped_column(Text)
    manifest_sha256: Mapped[str] = mapped_column(String(64))
    created_by: Mapped[str] = mapped_column(String(36), ForeignKey("report_review_users.user_id", ondelete="RESTRICT"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


class ClientReleaseAudit(Base):
    __tablename__ = "report_review_client_release_audits"

    audit_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    release_id: Mapped[str] = mapped_column(String(36), ForeignKey("report_review_client_releases.release_id", ondelete="RESTRICT"))
    admin_user_id: Mapped[str] = mapped_column(String(36), ForeignKey("report_review_users.user_id", ondelete="RESTRICT"))
    action: Mapped[str] = mapped_column(String(32))
    from_status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    to_status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class AuthSession(Base):
    __tablename__ = "report_review_sessions"
    __table_args__ = (Index("ix_report_review_sessions_user_active", "user_id", "revoked_at"),)

    session_id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("report_review_users.user_id", ondelete="CASCADE")
    )
    client_instance_id: Mapped[str] = mapped_column(String(128))
    refresh_token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_heartbeat_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)

    user: Mapped[User] = relationship(back_populates="sessions")


class Wallet(Base):
    __tablename__ = "report_review_wallets"

    user_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("report_review_users.user_id", ondelete="CASCADE"),
        primary_key=True,
    )
    balance: Mapped[Decimal] = mapped_column(Numeric(20, 8), default=Decimal("0.00000000"))
    currency: Mapped[str] = mapped_column(String(3), default="CNY")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class WalletLedger(Base):
    __tablename__ = "report_review_wallet_ledger"

    entry_id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("report_review_users.user_id", ondelete="CASCADE")
    )
    entry_type: Mapped[str] = mapped_column(String(32))
    amount: Mapped[Decimal] = mapped_column(Numeric(20, 8))
    balance_after: Mapped[Decimal] = mapped_column(Numeric(20, 8))
    reference_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    admin_user_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class ModelDefinition(Base):
    __tablename__ = "report_review_models"

    model_id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    code: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(128))
    tier: Mapped[str] = mapped_column(String(24))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    model_multiplier: Mapped[Decimal] = mapped_column(Numeric(12, 6), default=Decimal("1.000000"))
    max_output_tokens: Mapped[int] = mapped_column(Integer, default=8192)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class ProviderRoute(Base):
    __tablename__ = "report_review_provider_routes"
    __table_args__ = (UniqueConstraint("model_id", "priority", name="uq_provider_route_priority"),)

    route_id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    model_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("report_review_models.model_id", ondelete="CASCADE")
    )
    provider_type: Mapped[str] = mapped_column(String(32))
    provider_model: Mapped[str] = mapped_column(String(128))
    base_url: Mapped[str] = mapped_column(String(512))
    api_key_ciphertext: Mapped[str] = mapped_column(Text)
    priority: Mapped[int] = mapped_column(Integer)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    timeout_seconds: Mapped[int] = mapped_column(Integer, default=90)
    input_rate: Mapped[Decimal] = mapped_column(Numeric(20, 8))
    output_rate: Mapped[Decimal] = mapped_column(Numeric(20, 8))
    cache_hit_rate: Mapped[Decimal] = mapped_column(Numeric(20, 8))
    cache_miss_rate: Mapped[Decimal] = mapped_column(Numeric(20, 8))
    reasoning_rate: Mapped[Decimal] = mapped_column(Numeric(20, 8))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class BalanceHold(Base):
    __tablename__ = "report_review_balance_holds"
    __table_args__ = (
        UniqueConstraint("user_id", "client_request_id", name="uq_hold_user_request"),
    )

    hold_id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("report_review_users.user_id", ondelete="CASCADE")
    )
    model_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("report_review_models.model_id", ondelete="RESTRICT")
    )
    client_request_id: Mapped[str] = mapped_column(String(128))
    reserved_amount: Mapped[Decimal] = mapped_column(Numeric(20, 8))
    settled_amount: Mapped[Decimal] = mapped_column(Numeric(20, 8), default=Decimal("0.00000000"))
    status: Mapped[str] = mapped_column(String(16), default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class BillingRequest(Base):
    __tablename__ = "report_review_billing_requests"
    __table_args__ = (
        UniqueConstraint("user_id", "client_request_id", name="uq_billing_user_request"),
    )

    billing_request_id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("report_review_users.user_id", ondelete="CASCADE")
    )
    model_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("report_review_models.model_id", ondelete="RESTRICT")
    )
    hold_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("report_review_balance_holds.hold_id")
    )
    client_request_id: Mapped[str] = mapped_column(String(128))
    request_hash: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16), default="pending")
    charged_amount: Mapped[Decimal] = mapped_column(Numeric(20, 8), default=Decimal("0.00000000"))
    response_ciphertext: Mapped[str | None] = mapped_column(Text, nullable=True)
    response_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ProviderAttempt(Base):
    __tablename__ = "report_review_provider_attempts"
    __table_args__ = (
        UniqueConstraint(
            "billing_request_id",
            "attempt_number",
            name="uq_provider_attempt_number",
        ),
    )

    attempt_id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    billing_request_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("report_review_billing_requests.billing_request_id", ondelete="CASCADE"),
    )
    route_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("report_review_provider_routes.route_id")
    )
    attempt_number: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16))
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cache_hit_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cache_miss_tokens: Mapped[int] = mapped_column(Integer, default=0)
    reasoning_tokens: Mapped[int] = mapped_column(Integer, default=0)
    base_cost: Mapped[Decimal] = mapped_column(Numeric(20, 8))
    charged_amount: Mapped[Decimal] = mapped_column(Numeric(20, 8))
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class BillingReconciliation(Base):
    __tablename__ = "report_review_billing_reconciliations"

    reconciliation_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    hold_id: Mapped[str] = mapped_column(String(36), ForeignKey("report_review_balance_holds.hold_id", ondelete="RESTRICT"), unique=True)
    admin_user_id: Mapped[str] = mapped_column(String(36), ForeignKey("report_review_users.user_id", ondelete="RESTRICT"))
    confirmed_amount: Mapped[Decimal] = mapped_column(Numeric(20, 8))
    known_amount: Mapped[Decimal] = mapped_column(Numeric(20, 8))
    evidence_sha256: Mapped[str] = mapped_column(String(64))
    evidence_reference: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class ReviewJob(Base):
    __tablename__ = "report_review_jobs"
    __table_args__ = (
        UniqueConstraint("user_id", "client_job_id", name="uq_review_job_user_client"),
        Index("ix_review_jobs_context_expiry", "context_expires_at"),
        Index("ix_review_jobs_result_expiry", "result_expires_at"),
    )

    job_id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("report_review_users.user_id", ondelete="CASCADE")
    )
    model_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("report_review_models.model_id", ondelete="RESTRICT")
    )
    hold_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("report_review_balance_holds.hold_id", ondelete="RESTRICT")
    )
    client_job_id: Mapped[str] = mapped_column(String(128))
    round_number: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16), default="queued")
    context_hash: Mapped[str] = mapped_column(String(64))
    context_ciphertext: Mapped[str | None] = mapped_column(Text, nullable=True)
    context_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    execution_requested_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    worker_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    result_ciphertext: Mapped[str | None] = mapped_column(Text, nullable=True)
    result_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    batch_count: Mapped[int] = mapped_column(Integer, default=0)
    completed_batches: Mapped[int] = mapped_column(Integer, default=0)
    progress_percent: Mapped[int] = mapped_column(Integer, default=0)
    event_sequence: Mapped[int] = mapped_column(Integer, default=0)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ReviewJobEvent(Base):
    """Durable, metadata-only progress cursor for reconnecting clients."""

    __tablename__ = "report_review_job_events"
    __table_args__ = (
        UniqueConstraint("job_id", "sequence", name="uq_review_job_event_sequence"),
        Index("ix_review_job_events_cursor", "job_id", "sequence"),
    )

    event_id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    job_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("report_review_jobs.job_id", ondelete="CASCADE")
    )
    sequence: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(32))
    completed_batches: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
