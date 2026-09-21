"""Create encrypted server-side report-review jobs."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0003_review_jobs"
down_revision = "0002_billing"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "report_review_jobs",
        sa.Column("job_id", sa.String(36), nullable=False),
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("model_id", sa.String(36), nullable=False),
        sa.Column("hold_id", sa.String(36), nullable=False),
        sa.Column("client_job_id", sa.String(128), nullable=False),
        sa.Column("round_number", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("context_hash", sa.String(64), nullable=False),
        sa.Column("context_ciphertext", sa.Text(), nullable=True),
        sa.Column("context_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("result_ciphertext", sa.Text(), nullable=True),
        sa.Column("result_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("batch_count", sa.Integer(), nullable=False),
        sa.Column("completed_batches", sa.Integer(), nullable=False),
        sa.Column("progress_percent", sa.Integer(), nullable=False),
        sa.Column("error_code", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["hold_id"], ["report_review_balance_holds.hold_id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["model_id"], ["report_review_models.model_id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["report_review_users.user_id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("job_id"),
        sa.UniqueConstraint("user_id", "client_job_id", name="uq_review_job_user_client"),
    )
    op.create_index(
        "ix_review_jobs_context_expiry",
        "report_review_jobs",
        ["context_expires_at"],
    )
    op.create_index(
        "ix_review_jobs_result_expiry",
        "report_review_jobs",
        ["result_expires_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_review_jobs_result_expiry", table_name="report_review_jobs")
    op.drop_index("ix_review_jobs_context_expiry", table_name="report_review_jobs")
    op.drop_table("report_review_jobs")
