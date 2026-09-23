"""Add review job claim token used by the shutdown ownership fence."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0009_review_job_ownership"
down_revision = "0008_auth_refresh_rotation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "report_review_jobs",
        sa.Column("claim_token", sa.String(length=36), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("report_review_jobs", "claim_token")
