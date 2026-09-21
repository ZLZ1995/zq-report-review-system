"""Add durable review-job event cursors."""
import sqlalchemy as sa
from alembic import op

revision = "0006_review_job_events"
down_revision = "0005_client_releases"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "report_review_jobs",
        sa.Column("event_sequence", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "report_review_jobs",
        sa.Column("execution_requested_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "report_review_jobs",
        sa.Column("worker_id", sa.String(128), nullable=True),
    )
    op.add_column(
        "report_review_jobs",
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_table(
        "report_review_job_events",
        sa.Column("event_id", sa.String(36), primary_key=True),
        sa.Column(
            "job_id",
            sa.String(36),
            sa.ForeignKey("report_review_jobs.job_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("completed_batches", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("job_id", "sequence", name="uq_review_job_event_sequence"),
    )
    op.create_index(
        "ix_review_job_events_cursor",
        "report_review_job_events",
        ["job_id", "sequence"],
    )


def downgrade():
    op.drop_index("ix_review_job_events_cursor", table_name="report_review_job_events")
    op.drop_table("report_review_job_events")
    op.drop_column("report_review_jobs", "lease_expires_at")
    op.drop_column("report_review_jobs", "worker_id")
    op.drop_column("report_review_jobs", "execution_requested_at")
    op.drop_column("report_review_jobs", "event_sequence")
