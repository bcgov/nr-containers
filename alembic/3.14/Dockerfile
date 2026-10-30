FROM python:3.14-slim

# Generic Alembic/Flyway-style Oracle migration runner base.
# Ships only the Python runtime + shared deps (alembic, sqlalchemy, oracledb, jproperties, xxhash).
# No app runner, schema configs or SQL: consumers inject those after pull (see ../README.md).

ENV VIRTUAL_ENV=/opt/venv \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1

COPY runner/pyproject.toml runner/uv.lock /opt/runner/
RUN pip install --no-cache-dir uv \
    && uv sync --frozen --no-dev --no-install-project --project /opt/runner \
    && pip uninstall -y uv

# /app is the consumer workdir; world-writable so OpenShift's random UID can copy injected files in.
WORKDIR /app
RUN chmod 777 /app

CMD ["python", "-c", "import alembic, oracledb, sqlalchemy; print('alembic', alembic.__version__, 'oracledb', oracledb.__version__)"]
