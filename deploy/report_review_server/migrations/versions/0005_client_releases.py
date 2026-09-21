"""Add signed client release registry and admin audit."""
import sqlalchemy as sa
from alembic import op

revision = "0005_client_releases"
down_revision = "0004_billing_reconciliation"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("report_review_client_releases",
        sa.Column("release_id", sa.String(36), primary_key=True),
        sa.Column("version", sa.String(32), nullable=False), sa.Column("platform", sa.String(32), nullable=False),
        sa.Column("arch", sa.String(32), nullable=False), sa.Column("sequence", sa.Integer, nullable=False, unique=True),
        sa.Column("status", sa.String(16), nullable=False), sa.Column("manifest_json", sa.Text, nullable=False),
        sa.Column("manifest_sha256", sa.String(64), nullable=False),
        sa.Column("created_by", sa.String(36), sa.ForeignKey("report_review_users.user_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("version", "platform", "arch", name="uq_client_release_target"))
    op.create_index("ix_report_review_client_releases_version", "report_review_client_releases", ["version"])
    op.create_index("ix_report_review_client_releases_status", "report_review_client_releases", ["status"])
    op.create_table("report_review_client_release_audits",
        sa.Column("audit_id", sa.String(36), primary_key=True),
        sa.Column("release_id", sa.String(36), sa.ForeignKey("report_review_client_releases.release_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("admin_user_id", sa.String(36), sa.ForeignKey("report_review_users.user_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("action", sa.String(32), nullable=False), sa.Column("from_status", sa.String(16), nullable=True),
        sa.Column("to_status", sa.String(16), nullable=True), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))


def downgrade():
    count = op.get_bind().execute(sa.text("SELECT COUNT(*) FROM report_review_client_release_audits")).scalar()
    if count:
        raise RuntimeError("Cannot discard client release audit records")
    op.drop_table("report_review_client_release_audits")
    op.drop_index("ix_report_review_client_releases_status", table_name="report_review_client_releases")
    op.drop_index("ix_report_review_client_releases_version", table_name="report_review_client_releases")
    op.drop_table("report_review_client_releases")
