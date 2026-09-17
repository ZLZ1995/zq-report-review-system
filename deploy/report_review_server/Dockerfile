FROM python:3.12-slim

# CI may stamp the immutable source commit at build time. Zeabur/runtime
# environment variables can still override this value for a verified deploy.
ARG REPORT_REVIEW_BUILD_SHA=""
ARG ZEABUR_GIT_COMMIT_SHA=""

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src \
    REPORT_REVIEW_ENV=production \
    REPORT_REVIEW_BUILD_SHA=${REPORT_REVIEW_BUILD_SHA} \
    REPORT_REVIEW_IMAGE_BUILD_SHA=${ZEABUR_GIT_COMMIT_SHA}

WORKDIR /app
COPY deploy/report_review_server/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt
COPY src/asset_based_agent/__init__.py /app/src/asset_based_agent/__init__.py
COPY src/asset_based_agent /app/src/asset_based_agent
COPY deploy/report_review_server/alembic.ini /app/deploy/report_review_server/alembic.ini
COPY deploy/report_review_server/migrations /app/deploy/report_review_server/migrations
COPY scripts/bootstrap_report_review_admin.py /app/scripts/bootstrap_report_review_admin.py
COPY deploy/report_review_server/start.py /app/start.py

RUN useradd --create-home --uid 10001 appuser
USER appuser

EXPOSE 8000
CMD ["python", "/app/start.py"]
