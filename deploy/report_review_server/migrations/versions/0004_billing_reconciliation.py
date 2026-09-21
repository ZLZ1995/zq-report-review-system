"""Retain immutable evidence references for uncertain billing settlements."""
import sqlalchemy as sa
from alembic import op

revision = '0004_billing_reconciliation'
down_revision = '0003_review_jobs'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('report_review_billing_reconciliations',
        sa.Column('reconciliation_id', sa.String(36), primary_key=True),
        sa.Column('hold_id', sa.String(36), sa.ForeignKey('report_review_balance_holds.hold_id', ondelete='RESTRICT'), nullable=False, unique=True),
        sa.Column('admin_user_id', sa.String(36), sa.ForeignKey('report_review_users.user_id', ondelete='RESTRICT'), nullable=False),
        sa.Column('confirmed_amount', sa.Numeric(20, 8), nullable=False),
        sa.Column('known_amount', sa.Numeric(20, 8), nullable=False),
        sa.Column('evidence_sha256', sa.String(64), nullable=False),
        sa.Column('evidence_reference', sa.String(128), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False))


def downgrade():
    count = op.get_bind().execute(sa.text('SELECT COUNT(*) FROM report_review_billing_reconciliations')).scalar()
    if count:
        raise RuntimeError('Cannot discard billing reconciliation audit records')
    op.drop_table('report_review_billing_reconciliations')
