"""Add streaming liveness lease columns to billing requests."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0010_billing_stream_lease"
down_revision = "0009_review_job_ownership"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "report_review_billing_requests",
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "report_review_billing_requests",
        sa.Column("last_activity_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "report_review_billing_requests",
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("report_review_billing_requests", "lease_expires_at")
    op.drop_column("report_review_billing_requests", "last_activity_at")
    op.drop_column("report_review_billing_requests", "started_at")
