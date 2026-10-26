"""Add official SDK queue without altering existing account or billing tables."""
from alembic import op
from sqlalchemy import select,func
from zq_harness_gateway.finance_jobs import metadata,slots,jobs
revision='0012_official_finance_jobs'
down_revision='0011_finance_data'
branch_labels=None
depends_on=None
def upgrade():
    bind=op.get_bind();metadata.create_all(bind)
    if bind.execute(select(slots.c.id)).first() is None:bind.execute(slots.insert().values(id=1))
def downgrade():
    bind=op.get_bind()
    if bind.scalar(select(func.count()).select_from(jobs)):
        raise RuntimeError('Preserve query receipts; disable feature instead of dropping populated tables')
    metadata.drop_all(bind)
