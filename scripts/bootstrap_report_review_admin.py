"""Create the first report-review administrator from environment variables."""

from __future__ import annotations

import os

from asset_based_agent.report_review_server.config import ServerSettings
from asset_based_agent.report_review_server.database import (
    build_engine,
    build_session_factory,
)
from asset_based_agent.report_review_server.services.auth_service import (
    bootstrap_admin,
)


def main() -> int:
    settings = ServerSettings.from_environment()
    username = os.environ.get("REPORT_REVIEW_ADMIN_USERNAME", "").strip()
    password = os.environ.get("REPORT_REVIEW_ADMIN_PASSWORD", "")
    if not username or not password:
        raise RuntimeError(
            "REPORT_REVIEW_ADMIN_USERNAME and REPORT_REVIEW_ADMIN_PASSWORD are required"
        )
    admin = bootstrap_admin(
        build_session_factory(build_engine(settings.database_url)),
        username=username,
        password=password,
    )
    print(f"administrator-ready: {admin.username}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
