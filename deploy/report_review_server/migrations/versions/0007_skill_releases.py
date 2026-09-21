"""Add audited Skill release governance metadata."""
import sqlalchemy as sa
from alembic import op

revision = "0007_skill_releases"
down_revision = "0006_review_job_events"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "report_review_skill_releases",
        sa.Column("release_id", sa.String(36), primary_key=True),
        sa.Column("skill_id", sa.String(80), nullable=False),
        sa.Column("version", sa.String(32), nullable=False),
        sa.Column("package_sha256", sa.String(64), nullable=False),
        sa.Column("schema_version", sa.Integer, nullable=False),
        sa.Column("adapter", sa.String(64), nullable=False),
        sa.Column("capabilities_json", sa.Text, nullable=False),
        sa.Column("minimum_client_version", sa.String(32), nullable=False),
        sa.Column("evidence_sha256", sa.String(64), nullable=False),
        sa.Column("test_report_sha256", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("created_by", sa.String(36),
                  sa.ForeignKey("report_review_users.user_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("skill_id", "version", name="uq_skill_release_version"),
    )
    op.create_index("ix_report_review_skill_releases_skill_id",
                    "report_review_skill_releases", ["skill_id"])
    op.create_index("ix_report_review_skill_releases_status",
                    "report_review_skill_releases", ["status"])
    op.create_table(
        "report_review_skill_release_audits",
        sa.Column("audit_id", sa.String(36), primary_key=True),
        sa.Column("release_id", sa.String(36),
                  sa.ForeignKey("report_review_skill_releases.release_id", ondelete="RESTRICT"),
                  nullable=False),
        sa.Column("admin_user_id", sa.String(36),
                  sa.ForeignKey("report_review_users.user_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("action", sa.String(32), nullable=False),
        sa.Column("from_status", sa.String(16), nullable=True),
        sa.Column("to_status", sa.String(16), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade():
    bind = op.get_bind()
    if bind.execute(sa.text("SELECT COUNT(*) FROM report_review_skill_release_audits")).scalar():
        raise RuntimeError("Cannot discard Skill release audit records")
    if bind.execute(sa.text("SELECT COUNT(*) FROM report_review_skill_releases")).scalar():
        raise RuntimeError("Cannot discard Skill release records")
    op.drop_table("report_review_skill_release_audits")
    op.drop_index("ix_report_review_skill_releases_status",
                  table_name="report_review_skill_releases")
    op.drop_index("ix_report_review_skill_releases_skill_id",
                  table_name="report_review_skill_releases")
    op.drop_table("report_review_skill_releases")
