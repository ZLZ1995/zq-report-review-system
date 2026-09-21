"""Create wallets, models, routes, holds, and metered attempts."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0002_billing"
down_revision = "0001_auth"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "report_review_users",
        sa.Column(
            "billing_multiplier",
            sa.Numeric(12, 6),
            nullable=False,
            server_default="1.000000",
        ),
    )
    op.create_table(
        "report_review_wallets",
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("balance", sa.Numeric(20, 8), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["report_review_users.user_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id"),
    )
    op.execute(
        "INSERT INTO report_review_wallets (user_id, balance, currency, updated_at) "
        "SELECT user_id, 0, 'CNY', CURRENT_TIMESTAMP FROM report_review_users"
    )
    op.create_table(
        "report_review_wallet_ledger",
        sa.Column("entry_id", sa.String(36), nullable=False),
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("entry_type", sa.String(32), nullable=False),
        sa.Column("amount", sa.Numeric(20, 8), nullable=False),
        sa.Column("balance_after", sa.Numeric(20, 8), nullable=False),
        sa.Column("reference_id", sa.String(128), nullable=True),
        sa.Column("admin_user_id", sa.String(36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["report_review_users.user_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("entry_id"),
    )
    op.create_table(
        "report_review_models",
        sa.Column("model_id", sa.String(36), nullable=False),
        sa.Column("code", sa.String(64), nullable=False),
        sa.Column("display_name", sa.String(128), nullable=False),
        sa.Column("tier", sa.String(24), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("model_multiplier", sa.Numeric(12, 6), nullable=False),
        sa.Column("max_output_tokens", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("model_id"),
    )
    op.create_index(
        "ix_report_review_models_code",
        "report_review_models",
        ["code"],
        unique=True,
    )
    op.create_table(
        "report_review_provider_routes",
        sa.Column("route_id", sa.String(36), nullable=False),
        sa.Column("model_id", sa.String(36), nullable=False),
        sa.Column("provider_type", sa.String(32), nullable=False),
        sa.Column("provider_model", sa.String(128), nullable=False),
        sa.Column("base_url", sa.String(512), nullable=False),
        sa.Column("api_key_ciphertext", sa.Text(), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("timeout_seconds", sa.Integer(), nullable=False),
        sa.Column("input_rate", sa.Numeric(20, 8), nullable=False),
        sa.Column("output_rate", sa.Numeric(20, 8), nullable=False),
        sa.Column("cache_hit_rate", sa.Numeric(20, 8), nullable=False),
        sa.Column("cache_miss_rate", sa.Numeric(20, 8), nullable=False),
        sa.Column("reasoning_rate", sa.Numeric(20, 8), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["model_id"], ["report_review_models.model_id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("route_id"),
        sa.UniqueConstraint("model_id", "priority", name="uq_provider_route_priority"),
    )
    op.create_table(
        "report_review_balance_holds",
        sa.Column("hold_id", sa.String(36), nullable=False),
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("model_id", sa.String(36), nullable=False),
        sa.Column("client_request_id", sa.String(128), nullable=False),
        sa.Column("reserved_amount", sa.Numeric(20, 8), nullable=False),
        sa.Column("settled_amount", sa.Numeric(20, 8), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["model_id"], ["report_review_models.model_id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["report_review_users.user_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("hold_id"),
        sa.UniqueConstraint("user_id", "client_request_id", name="uq_hold_user_request"),
    )
    op.create_table(
        "report_review_billing_requests",
        sa.Column("billing_request_id", sa.String(36), nullable=False),
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("model_id", sa.String(36), nullable=False),
        sa.Column("hold_id", sa.String(36), nullable=False),
        sa.Column("client_request_id", sa.String(128), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("charged_amount", sa.Numeric(20, 8), nullable=False),
        sa.Column("response_ciphertext", sa.Text(), nullable=True),
        sa.Column("response_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_code", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["hold_id"], ["report_review_balance_holds.hold_id"]),
        sa.ForeignKeyConstraint(
            ["model_id"], ["report_review_models.model_id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["report_review_users.user_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("billing_request_id"),
        sa.UniqueConstraint("user_id", "client_request_id", name="uq_billing_user_request"),
    )
    op.create_table(
        "report_review_provider_attempts",
        sa.Column("attempt_id", sa.String(36), nullable=False),
        sa.Column("billing_request_id", sa.String(36), nullable=False),
        sa.Column("route_id", sa.String(36), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False),
        sa.Column("output_tokens", sa.Integer(), nullable=False),
        sa.Column("cache_hit_tokens", sa.Integer(), nullable=False),
        sa.Column("cache_miss_tokens", sa.Integer(), nullable=False),
        sa.Column("reasoning_tokens", sa.Integer(), nullable=False),
        sa.Column("base_cost", sa.Numeric(20, 8), nullable=False),
        sa.Column("charged_amount", sa.Numeric(20, 8), nullable=False),
        sa.Column("error_code", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["billing_request_id"],
            ["report_review_billing_requests.billing_request_id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["route_id"], ["report_review_provider_routes.route_id"]),
        sa.PrimaryKeyConstraint("attempt_id"),
        sa.UniqueConstraint(
            "billing_request_id",
            "attempt_number",
            name="uq_provider_attempt_number",
        ),
    )


def downgrade() -> None:
    op.drop_table("report_review_provider_attempts")
    op.drop_table("report_review_billing_requests")
    op.drop_table("report_review_balance_holds")
    op.drop_table("report_review_provider_routes")
    op.drop_index("ix_report_review_models_code", table_name="report_review_models")
    op.drop_table("report_review_models")
    op.drop_table("report_review_wallet_ledger")
    op.drop_table("report_review_wallets")
    op.drop_column("report_review_users", "billing_multiplier")
