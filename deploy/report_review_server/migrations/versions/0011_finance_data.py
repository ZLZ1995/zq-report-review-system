"""Add shared encrypted data credential and account-scoped query receipts."""
import sqlalchemy as sa
from alembic import op

revision = '0011_finance_data'
down_revision = '0010_billing_stream_lease'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('report_review_finance_credentials',
                    sa.Column('provider', sa.String(32), primary_key=True),
                    sa.Column('ciphertext', sa.Text(), nullable=False),
                    sa.Column('updated_by', sa.String(36), sa.ForeignKey('report_review_users.user_id'), nullable=False),
                    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False))
    op.create_table('report_review_finance_requests',
                    sa.Column('user_id', sa.String(36), sa.ForeignKey('report_review_users.user_id'), primary_key=True),
                    sa.Column('request_id', sa.String(64), primary_key=True),
                    sa.Column('request_hash', sa.String(64), nullable=False),
                    sa.Column('status', sa.String(16), nullable=False),
                    sa.Column('result_ciphertext', sa.Text(), nullable=True),
                    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False))


def downgrade():
    bind = op.get_bind()
    for table in ('report_review_finance_requests', 'report_review_finance_credentials'):
        if bind.execute(sa.text('SELECT COUNT(*) FROM ' + table)).scalar():
            raise RuntimeError('Cannot discard financial data configuration or query receipts')
    op.drop_table('report_review_finance_requests')
    op.drop_table('report_review_finance_credentials')
