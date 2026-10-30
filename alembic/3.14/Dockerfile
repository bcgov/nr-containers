FROM python:3.14-slim

# Alembic/Flyway-compatible migration runner for bcgov-c/nr-mof-db.
# Runner code only: SQL migrations stay in nr-mof-db and are mounted at runtime (scripts PVC).
WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

ENV UV_PROJECT_ENVIRONMENT=/app/utils/.venv
ENV PATH="/app/utils/.venv/bin:$PATH"

COPY utils/pyproject.toml utils/uv.lock /app/utils/
RUN pip install --no-cache-dir uv && uv sync --frozen --no-dev --project /app/utils

COPY alembic/ /app/alembic
COPY alembic.sh migration_driver.sh run_all_migrations.sh run_timestamp_migrations.sh /app/

RUN chmod -R 777 /app && \
    chmod +x /app/alembic/verify_pr_rollback.py /app/*.sh && \
    ln -s /app/alembic/verify_pr_rollback.py /app/verify_pr_rollback.py

CMD ["/bin/bash", "-lc", "/app/alembic.sh help"]
