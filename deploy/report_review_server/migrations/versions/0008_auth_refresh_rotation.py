"""Add refresh-token rotation fields used by the current auth service."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0008_auth_refresh_rotation"
down_revision = "0007_skill_releases"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "report_review_sessions",
        sa.Column("previous_refresh_token_hash", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "report_review_sessions",
        sa.Column("refresh_rotated_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("report_review_sessions", "refresh_rotated_at")
    op.drop_column("report_review_sessions", "previous_refresh_token_hash")
