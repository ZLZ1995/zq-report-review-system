from __future__ import annotations

import sqlite3
from pathlib import Path

from alembic import command
from alembic.config import Config

ROOT = Path(__file__).resolve().parents[2]


def test_billing_migration_backfills_existing_user_wallet(tmp_path: Path) -> None:
    database_path = tmp_path / "migration.db"
    config = Config(str(ROOT / "deploy" / "report_review_server" / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", f"sqlite+pysqlite:///{database_path.as_posix()}")
    command.upgrade(config, "0001_auth")
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """
            INSERT INTO report_review_users (
                user_id, username, display_name, email, password_hash, role,
                status, must_change_password, registration_source,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """,
            (
                "USER-1",
                "existing",
                "Existing User",
                None,
                "hash",
                "user",
                "active",
                1,
                "admin",
            ),
        )
    command.upgrade(config, "head")
    with sqlite3.connect(database_path) as connection:
        wallet = connection.execute(
            "SELECT balance, currency FROM report_review_wallets WHERE user_id = ?",
            ("USER-1",),
        ).fetchone()
        multiplier = connection.execute(
            "SELECT billing_multiplier FROM report_review_users WHERE user_id = ?",
            ("USER-1",),
        ).fetchone()

    assert wallet == (0, "CNY")
    assert multiplier == (1,)
    command.downgrade(config, "base")
