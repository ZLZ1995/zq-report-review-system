# Report Review Server Deployment

This directory contains the first deployable control-plane skeleton. It does not
yet contain billing, model routing, or the server-side review agent.

## Required secrets

- `REPORT_REVIEW_DATABASE_URL`
- `REPORT_REVIEW_JWT_SECRET` with at least 32 random characters
- `REPORT_REVIEW_ADMIN_USERNAME` for initial bootstrap only
- `REPORT_REVIEW_ADMIN_PASSWORD` for initial bootstrap only

Never commit populated secret files. Remove the bootstrap password from the
runtime environment after the first administrator has been created.

## Deployment order

1. Provision a private PostgreSQL service.
2. Build the image from the repository root using this Dockerfile.
3. Run Alembic migrations with `alembic upgrade head`.
4. Run `scripts/bootstrap_report_review_admin.py` once.
5. Start the ASGI service behind the Zeabur HTTPS ingress.
6. Verify `/api/v1/health` without exposing database details.

The production application intentionally does not create database tables on
startup. Schema changes must go through versioned Alembic migrations.
