from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
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


def test_reconciliation_migration_refuses_audit_loss(tmp_path):
    path = tmp_path / 'audit.db'
    config = Config(str(ROOT / 'deploy' / 'report_review_server' / 'alembic.ini'))
    config.set_main_option('sqlalchemy.url', f'sqlite+pysqlite:///{path.as_posix()}')
    command.upgrade(config, 'head')
    # Synthetic row tests the downgrade retention gate, not FK integrity.
    with sqlite3.connect(path) as db:
        db.execute('''INSERT INTO report_review_billing_reconciliations
            (reconciliation_id, hold_id, admin_user_id, confirmed_amount, known_amount,
             evidence_sha256, evidence_reference, created_at)
            VALUES ('r', 'h', 'a', 0, 0, ?, 'TEST-001', CURRENT_TIMESTAMP)''', ('a'*64,))
    with pytest.raises(RuntimeError, match='audit records'):
        command.downgrade(config, '0003_review_jobs')
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT COUNT(*) FROM report_review_billing_reconciliations').fetchone()[0] == 1


def test_skill_release_migration_is_head_and_contains_audit_tables(tmp_path):
    path = tmp_path / "skill-release.db"
    config = Config(str(ROOT / "deploy" / "report_review_server" / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", f"sqlite+pysqlite:///{path.as_posix()}")
    command.upgrade(config, "head")
    with sqlite3.connect(path) as db:
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert {"report_review_skill_releases", "report_review_skill_release_audits"} <= tables
        assert db.execute("SELECT version_num FROM alembic_version").fetchone()[0] == "0007_skill_releases"
