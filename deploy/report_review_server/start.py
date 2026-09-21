"""Single-instance deployment bootstrap. Refuse to serve after failed migration."""
import os
import subprocess
import sys


def main():
    from asset_based_agent.report_review_server.config import ServerSettings

    settings = ServerSettings.from_environment()
    if not settings.database_url.startswith("postgresql+psycopg://"):
        raise RuntimeError("Cloud deployment requires postgresql+psycopg:// database URL")
    port = int(os.environ.get("PORT", "8000"))
    if not 1 <= port <= 65535:
        raise ValueError("Invalid PORT")
    subprocess.run([sys.executable, "-m", "alembic", "-c",
                    "/app/deploy/report_review_server/alembic.ini", "upgrade", "head"], check=True)
    if os.environ.get("REPORT_REVIEW_ADMIN_USERNAME") or os.environ.get("REPORT_REVIEW_ADMIN_PASSWORD"):
        subprocess.run([sys.executable, "/app/scripts/bootstrap_report_review_admin.py"], check=True)
    os.execvp(sys.executable, [sys.executable, "-m", "uvicorn",
        "asset_based_agent.report_review_server.main:app", "--host", "0.0.0.0",
        "--port", str(port)])


if __name__ == "__main__":
    main()
