FROM python:3.14-slim
# Published tag comes from the FROM tag above; keep pinned to 3.14-slim until 3.15 wheels are ready.

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

# Login shells (bash -l / bash -lc) source /etc/profile, which resets PATH and
# drops the venv. /etc/profile.d/*.sh is sourced afterwards, so prepend it here.
# World-readable: OpenShift runs as a random non-root UID with no home directory.
RUN printf '%s\n' 'export PATH="/opt/venv/bin${PATH:+:$PATH}"' > /etc/profile.d/venv.sh \
    && chmod 644 /etc/profile.d/venv.sh

# /app is the consumer workdir; world-writable so OpenShift's random UID can copy injected files in.
WORKDIR /app
RUN chmod 777 /app

CMD ["python", "-c", "import alembic, oracledb, sqlalchemy; print('alembic', alembic.__version__, 'oracledb', oracledb.__version__)"]
